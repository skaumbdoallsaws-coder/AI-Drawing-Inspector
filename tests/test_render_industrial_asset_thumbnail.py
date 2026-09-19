import hashlib
import importlib.util
import json
import re
import struct
from pathlib import Path

import pytest
from PIL import Image

from ai_inspector.industrial_assets.artifacts import build_aabb_proxy_glb


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "render_industrial_asset_thumbnail.py"
EVIDENCE_DIRECTORY = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "assets"
)


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "render_industrial_asset_thumbnail", TOOL_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RENDERER = _load_tool()


def _chunk(chunk_type: int, payload: bytes, padding: bytes) -> bytes:
    padded_length = (len(payload) + 3) & ~3
    padded = payload + padding * (padded_length - len(payload))
    return struct.pack("<II", padded_length, chunk_type) + padded


def _write_glb(path: Path, *, with_cube: bool) -> None:
    if not with_cube:
        document = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": []}],
        }
        chunks = [_chunk(0x4E4F534A, json.dumps(document).encode("ascii"), b" ")]
    else:
        positions = (
            -1.0,
            -1.0,
            -1.0,
            1.0,
            -1.0,
            -1.0,
            1.0,
            1.0,
            -1.0,
            -1.0,
            1.0,
            -1.0,
            -1.0,
            -1.0,
            1.0,
            1.0,
            -1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            -1.0,
            1.0,
            1.0,
        )
        indices = (
            0,
            1,
            2,
            0,
            2,
            3,
            4,
            6,
            5,
            4,
            7,
            6,
            0,
            4,
            5,
            0,
            5,
            1,
            1,
            5,
            6,
            1,
            6,
            2,
            2,
            6,
            7,
            2,
            7,
            3,
            3,
            7,
            4,
            3,
            4,
            0,
        )
        position_bytes = struct.pack("<24f", *positions)
        index_bytes = struct.pack("<36H", *indices)
        binary = position_bytes + index_bytes
        document = {
            "accessors": [
                {
                    "bufferView": 0,
                    "componentType": 5126,
                    "count": 8,
                    "max": [1, 1, 1],
                    "min": [-1, -1, -1],
                    "type": "VEC3",
                },
                {
                    "bufferView": 1,
                    "componentType": 5123,
                    "count": 36,
                    "type": "SCALAR",
                },
            ],
            "asset": {
                "generator": "InspectorPro thumbnail test",
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
            "buffers": [{"byteLength": len(binary)}],
            "materials": [
                {
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [0.05, 0.55, 0.72, 1],
                        "metallicFactor": 0.15,
                        "roughnessFactor": 0.55,
                    }
                }
            ],
            "meshes": [
                {
                    "primitives": [
                        {
                            "attributes": {"POSITION": 0},
                            "indices": 1,
                            "material": 0,
                            "mode": 4,
                        }
                    ]
                }
            ],
            "nodes": [{"mesh": 0}],
            "scene": 0,
            "scenes": [{"nodes": [0]}],
        }
        chunks = [
            _chunk(0x4E4F534A, json.dumps(document).encode("ascii"), b" "),
            _chunk(0x004E4942, binary, b"\x00"),
        ]
    total_length = 12 + sum(len(chunk) for chunk in chunks)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total_length) + b"".join(chunks)
    )


def test_glb_container_validation_rejects_corruption_and_bounds(tmp_path):
    valid = tmp_path / "valid.glb"
    _write_glb(valid, with_cube=True)
    metadata = RENDERER.validate_glb_container(valid)
    assert metadata["version"] == 2
    assert metadata["byteLength"] == valid.stat().st_size
    assert metadata["sha256"] == hashlib.sha256(valid.read_bytes()).hexdigest()

    corrupt = tmp_path / "corrupt.glb"
    corrupt.write_bytes(b"not a glb")
    with pytest.raises(RENDERER.ThumbnailRenderError, match="too short"):
        RENDERER.validate_glb_container(corrupt)
    with pytest.raises(RENDERER.ThumbnailRenderError, match="exceeds"):
        RENDERER.validate_glb_container(
            valid, maximum_input_bytes=valid.stat().st_size - 1
        )


def test_offline_renderer_is_nonblank_bounded_and_repeatable(tmp_path):
    source = tmp_path / "cube.glb"
    evidence_path = tmp_path / "evidence.json"
    _write_glb(source, with_cube=True)

    evidence_records = []
    output_paths = []
    for index in range(6):
        output = tmp_path / f"repeat-{index}.png"
        output_paths.append(output)
        evidence_records.append(
            RENDERER.render_industrial_asset_thumbnail(
                source,
                output,
                evidence_path=evidence_path if index == 0 else None,
                width=320,
                height=240,
            )
        )

    first_evidence = evidence_records[0]
    assert len({output.read_bytes() for output in output_paths}) == 1
    assert {evidence["output"]["sha256"] for evidence in evidence_records} == {
        first_evidence["output"]["sha256"]
    }
    assert {
        evidence["renderer"]["renderPlanSha256"]
        for evidence in evidence_records
    } == {first_evidence["renderer"]["renderPlanSha256"]}
    for evidence in evidence_records:
        assert evidence["passed"] is True
        assert evidence["checks"]["localAssetsOnly"] is True
        assert evidence["checks"]["inputTransferFinished"] is True
        assert evidence["geometry"]["meshCount"] == 1
        assert evidence["geometry"]["triangleCount"] == 12
        assert evidence["output"]["pixelValidation"]["nonblank"] is True
        assert evidence["network"] == {
            "externalRequestCount": 0,
            "failedRequestCount": 0,
            "failedResponseCount": 0,
            "offlineOnly": True,
        }
    with Image.open(output_paths[0]) as image:
        image.load()
        assert image.format == "PNG"
        assert image.size == (320, 240)
    assert json.loads(evidence_path.read_text(encoding="ascii")) == first_evidence


def test_renderer_applies_source_transform_before_bounds_and_framing(tmp_path):
    source = tmp_path / "long-z-up.glb"
    source.write_bytes(build_aabb_proxy_glb({
        "minimum": {"x": -1.0, "y": -3.0, "z": 0.0},
        "maximum": {"x": 1.0, "y": 3.0, "z": 1.0},
    }))
    output = tmp_path / "upright.png"
    rotate_x_negative_90 = [
        1.0, 0.0, 0.0, 0.0,
        0.0, 0.0, -1.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]

    evidence = RENDERER.render_industrial_asset_thumbnail(
        source,
        output,
        width=320,
        height=240,
        source_transform=rotate_x_negative_90,
    )

    assert evidence["geometry"]["bounds"]["size"] == pytest.approx(
        [2.0, 1.0, 6.0]
    )
    assert evidence["renderer"]["sourceTransform"] == rotate_x_negative_90
    assert evidence["passed"] is True


def test_genuine_local_module_failure_is_fatal(tmp_path, monkeypatch):
    source = tmp_path / "cube.glb"
    output = tmp_path / "should-not-exist.png"
    _write_glb(source, with_cube=True)
    original_make_handler = RENDERER._make_handler

    def failing_make_handler(*, renderer_page):
        base_handler = original_make_handler(renderer_page=renderer_page)

        class FailingModuleHandler(base_handler):
            def do_GET(self):
                if self.path.endswith("/build/three.module.min.js"):
                    self.send_error(503, "injected module failure")
                    return
                super().do_GET()

        return FailingModuleHandler

    monkeypatch.setattr(RENDERER, "_make_handler", failing_make_handler)
    with pytest.raises(
        RENDERER.ThumbnailRenderError,
        match="Timed out while rendering",
    ):
        RENDERER.render_industrial_asset_thumbnail(
            source,
            output,
            width=256,
            height=256,
            timeout_ms=2_000,
        )
    assert not output.exists()


def test_renderer_fails_closed_for_valid_but_blank_glb(tmp_path):
    source = tmp_path / "blank.glb"
    output = tmp_path / "blank.png"
    _write_glb(source, with_cube=False)

    with pytest.raises(
        RENDERER.ThumbnailRenderError,
        match="GLB_HAS_NO_RENDERABLE_TRIANGLES",
    ):
        RENDERER.render_industrial_asset_thumbnail(
            source,
            output,
            width=256,
            height=256,
        )
    assert not output.exists()


@pytest.mark.parametrize(
    ("evidence_name", "source_name", "minimum_source_bytes"),
    (
        (
            "toyota-forklift-thumbnail-evidence.json",
            "User Library-Toyota Forklift_colored.glb",
            100_000,
        ),
        (
            "pallet-racking-thumbnail-evidence.json",
            "Pallet Racking_colored.glb",
            10_000_000,
        ),
    ),
)
def test_checked_in_real_asset_evidence_is_source_control_safe(
    evidence_name,
    source_name,
    minimum_source_bytes,
):
    evidence_path = EVIDENCE_DIRECTORY / evidence_name
    evidence = json.loads(evidence_path.read_text(encoding="ascii"))
    serialized = json.dumps(evidence, ensure_ascii=True, sort_keys=True)
    assert evidence["schemaVersion"] == "industrial-asset-thumbnail-evidence-v1"
    assert evidence["passed"] is True
    assert all(evidence["checks"].values())
    assert evidence["source"]["artifactName"] == source_name
    assert evidence["source"]["byteLength"] > minimum_source_bytes
    assert re.fullmatch(r"[0-9a-f]{64}", evidence["source"]["sha256"])
    assert evidence["output"]["artifactName"] == "thumbnail.png"
    assert evidence["output"]["mediaType"] == "image/png"
    assert evidence["output"]["pixelValidation"]["nonblank"] is True
    assert evidence["network"]["offlineOnly"] is True
    assert evidence["network"]["externalRequestCount"] == 0
    assert evidence["renderer"]["runnerSha256"] == hashlib.sha256(
        TOOL_PATH.read_bytes()
    ).hexdigest()
    assert re.search(r"[A-Za-z]:\\\\", serialized) is None
    assert str(ROOT.parent) not in serialized
