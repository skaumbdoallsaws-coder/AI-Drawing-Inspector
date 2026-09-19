from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from ai_inspector.assembly_knowledge import (
    VisualEvidenceError,
    adapt_bridge_package,
    ingest_solidworks_visuals,
    occurrence_alias_map,
    render_glb_identity_masks,
    write_occurrence_map_tsv,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "packages"
    / "bridge-v1.0"
)


def _adapt(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    root = source / "SWPR-Tricycle.SLDASM"
    root.write_bytes(b"assembly")
    (source / "Wheel.SLDPRT").write_bytes(b"wheel")
    (source / "Axle.SLDPRT").write_bytes(b"axle")
    return adapt_bridge_package(
        FIXTURE,
        source_root=source,
        root_assembly=root,
        product_id="tricycle",
    )


def _image(path: Path, colors: list[str], *, size=(240, 160)) -> None:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    width = max(20, size[0] // (len(colors) + 1))
    for index, color in enumerate(colors):
        left = 20 + index * width
        draw.rectangle((left, 30, left + width - 8, size[1] - 30), fill=color)
    # Save as BMP under the legacy .png spelling to test real normalization.
    image.save(path, format="BMP")


def _tiny_glb(path: Path) -> None:
    positions = struct.pack(
        "<18f",
        -1.0,
        -1.0,
        0.0,
        -0.1,
        -1.0,
        0.0,
        -0.5,
        1.0,
        0.0,
        0.1,
        -1.0,
        0.2,
        1.0,
        -1.0,
        0.2,
        0.5,
        1.0,
        0.2,
    )
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0, 1]}],
        "nodes": [
            {"name": "Wheel-1", "mesh": 0},
            {"name": "Wheel-2", "mesh": 1},
        ],
        "meshes": [
            {"primitives": [{"attributes": {"POSITION": 0}}]},
            {"primitives": [{"attributes": {"POSITION": 1}}]},
        ],
        "buffers": [{"byteLength": len(positions)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 36},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
        ],
    }
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((-len(json_chunk)) % 4)
    bin_chunk = positions + b"\0" * ((-len(positions)) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
        + struct.pack("<II", len(bin_chunk), 0x004E4942)
        + bin_chunk
    )


def test_occurrence_map_uses_aliases_and_distinguishes_repeated_parts(
    tmp_path: Path,
) -> None:
    adapted = _adapt(tmp_path)
    aliases = occurrence_alias_map(adapted.documents["product_structure.json"])
    assert set(aliases) == {"Wheel-1", "Wheel-2", "Axle-1"}
    assert aliases["Wheel-1"] != aliases["Wheel-2"]
    path = write_occurrence_map_tsv(
        adapted.documents["product_structure.json"],
        tmp_path / "occurrences.tsv",
    )
    assert path.read_text("ascii").count("\n") == 4


def test_visual_ingestion_pairs_views_validates_masks_and_hashes_assets(
    tmp_path: Path,
) -> None:
    adapted = _adapt(tmp_path)
    aliases = occurrence_alias_map(adapted.documents["product_structure.json"])
    colors = ["#2050A0", "#A05020", "#20A050"]
    capture = tmp_path / "capture"
    capture.mkdir()
    for view in ("front", "top", "right", "isometric"):
        _image(capture / f"Fixture_view_{view}.png", ["#303030"])
        _image(capture / f"Fixture_identity_mask_view_{view}.png", colors)
    lines = ["# hexColor\tcomponentAlias\toccurrenceId"]
    for color, (alias, occurrence_id) in zip(colors, sorted(aliases.items())):
        lines.append(f"{color}\t{alias}\t{occurrence_id}")
    (capture / "Fixture_identity_mask_legend.tsv").write_text(
        "\n".join(lines) + "\n", "ascii"
    )
    glb = capture / "Fixture.glb"
    glb.write_bytes(b"glTF fixture")

    documents, assets = ingest_solidworks_visuals(
        adapted.documents,
        capture_dir=capture,
        assembly_base_name="Fixture",
        glb_path=glb,
    )
    manifest = documents["visual_manifest.json"]
    assert len(manifest["views"]) == 4
    assert all(len(item["visibleOccurrenceIds"]) == 3 for item in manifest["views"])
    assert "visuals/assembly.glb" in assets
    assert documents["package.json"]["assetHashes"]["visuals/assembly.glb"]
    for payload in assets.values():
        assert isinstance(payload, bytes) and payload
    with Image.open(io.BytesIO(assets["visuals/presentation/front.png"])) as image:
        assert image.format == "PNG"


def test_visual_ingestion_rejects_dimension_mismatch(tmp_path: Path) -> None:
    adapted = _adapt(tmp_path)
    aliases = occurrence_alias_map(adapted.documents["product_structure.json"])
    capture = tmp_path / "capture"
    capture.mkdir()
    colors = ["#2050A0", "#A05020", "#20A050"]
    lines = ["# hexColor\tcomponentAlias\toccurrenceId"]
    for color, (alias, occurrence_id) in zip(colors, sorted(aliases.items())):
        lines.append(f"{color}\t{alias}\t{occurrence_id}")
    (capture / "Fixture_identity_mask_legend.tsv").write_text(
        "\n".join(lines) + "\n", "ascii"
    )
    for view in ("front", "top", "right", "isometric"):
        _image(capture / f"Fixture_view_{view}.png", ["#303030"])
        _image(
            capture / f"Fixture_identity_mask_view_{view}.png",
            colors,
            size=(200, 160) if view == "front" else (240, 160),
        )
    with pytest.raises(VisualEvidenceError, match="dimensions differ"):
        ingest_solidworks_visuals(
            adapted.documents,
            capture_dir=capture,
            assembly_base_name="Fixture",
        )


def test_glb_identity_renderer_distinguishes_repeated_occurrences(
    tmp_path: Path,
) -> None:
    glb = tmp_path / "fixture.glb"
    _tiny_glb(glb)
    entries = [
        {
            "componentAlias": "Wheel-1",
            "occurrenceId": "occ-wheel-1",
            "hexColor": "#2050A0",
        },
        {
            "componentAlias": "Wheel-2",
            "occurrenceId": "occ-wheel-2",
            "hexColor": "#A05020",
        },
    ]
    paths = render_glb_identity_masks(
        glb,
        entries,
        output_dir=tmp_path,
        assembly_base_name="Fixture",
        dimensions_by_view={
            "front": (160, 120),
            "top": (160, 120),
            "right": (160, 120),
            "isometric": (160, 120),
        },
    )
    assert set(paths) == {"front", "top", "right", "isometric"}
    with Image.open(paths["front"]).convert("RGB") as image:
        colors = set(image.getdata())
    assert (32, 80, 160) in colors
    assert (160, 80, 32) in colors
