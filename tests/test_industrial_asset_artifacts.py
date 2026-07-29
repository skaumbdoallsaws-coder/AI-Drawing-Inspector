from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
import math
from pathlib import Path
import struct

from PIL import Image
import pytest

from ai_inspector.industrial_assets.artifacts import (
    ArtifactValidationError,
    GlbInspection,
    build_aabb_proxy_glb,
    build_render_bundle_manifest,
    derive_geometry_candidates,
    detect_image_format,
    inspect_glb,
    normalize_web_image,
    validate_lod_set,
    validate_render_artifact_sources,
)
from ai_inspector.industrial_assets.schema_v1 import canonical_json_bytes


ROOT = Path(__file__).resolve().parents[1]
P0_ROOT = ROOT / "generated" / "industrial_assets" / "p0_spike"
EVIDENCE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "assets"
    / "p0-normalization-evidence.json"
)
NORMALIZED_ROOT = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "assets"
)
GEOMETRY_INTERFACE_REVISION = (
    "c8b9dd44c45266ba501b3116856fae43657ce31f6c7bbf8bedaa357e70a5717d"
)


def _real_paths() -> dict[str, dict[str, Path]]:
    return {
        "cnc": {
            "glb": (
                P0_ROOT
                / "cnc_vmc"
                / "User Library-CNC Milling machine_colored.glb"
            ),
            "image": (
                P0_ROOT
                / "cnc_vmc"
                / "User Library-CNC Milling machine_view_isometric.png"
            ),
            "extracted": P0_ROOT / "cnc_vmc" / "extracted.json",
            "normalized": (
                NORMALIZED_ROOT / "cnc-vmc-milling-machine.normalized-p0.json"
            ),
        },
        "workstation": {
            "glb": (
                P0_ROOT
                / "wa01_workstation"
                / "RF--WA01-W48-D36-H34-T0_375-UF-F0-P5002_colored.glb"
            ),
            "image": (
                P0_ROOT
                / "wa01_workstation"
                / "RF--WA01-W48-D36-H34-T0_375-UF-F0-P5002_view_isometric.png"
            ),
            "extracted": P0_ROOT / "wa01_workstation" / "extracted.json",
            "normalized": (
                NORMALIZED_ROOT
                / "wa01-w48-d36-machine-table.normalized-p0.json"
            ),
        },
    }


def _require_real_p0() -> dict[str, dict[str, Path]]:
    paths = _real_paths()
    missing = [
        str(path)
        for record in paths.values()
        for path in record.values()
        if not path.exists()
    ]
    if missing:
        pytest.skip("P0 local extraction fixtures are unavailable")
    return paths


def _minimal_glb(
    *,
    positions: tuple[tuple[float, float, float], ...] = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 1.0),
    ),
    declared_minimum: tuple[float, float, float] | None = None,
    declared_maximum: tuple[float, float, float] | None = None,
    translation: tuple[float, float, float] | None = None,
) -> bytes:
    binary = b"".join(struct.pack("<fff", *point) for point in positions)
    while len(binary) % 4:
        binary += b"\x00"
    minimum = declared_minimum or tuple(
        min(point[axis] for point in positions) for axis in range(3)
    )
    maximum = declared_maximum or tuple(
        max(point[axis] for point in positions) for axis in range(3)
    )
    node = {"mesh": 0}
    if translation is not None:
        node["translation"] = list(translation)
    document = {
        "asset": {"version": "2.0", "generator": "test"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(binary)}
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(positions),
                "type": "VEC3",
                "min": list(minimum),
                "max": list(maximum),
            }
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "nodes": [node],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    json_bytes = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    json_bytes += b" " * ((-len(json_bytes)) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(binary)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(json_bytes), b"JSON")
        + json_bytes
        + struct.pack("<I4s", len(binary), b"BIN\x00")
        + binary
    )


def _nonblank_png_bytes() -> bytes:
    image = Image.new("RGB", (48, 32), "white")
    for x in range(8, 40):
        for y in range(6, 26):
            image.putpixel((x, y), (20, 90 + x, 180 - y))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _synthetic_render_bundle_sources(
    tmp_path: Path,
) -> tuple[dict, dict[str, Path]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    glb_data = _minimal_glb()
    glb = inspect_glb(glb_data)
    thumbnail = normalize_web_image(_nonblank_png_bytes())
    texture_data = _nonblank_png_bytes()
    texture = {
        "mediaType": "image/png",
        "byteLength": len(texture_data),
        "sha256": _sha256(texture_data),
    }
    bundle = build_render_bundle_manifest(
        asset_id="asset-publication-test",
        geometry_interface_revision=GEOMETRY_INTERFACE_REVISION,
        lods={"lod0": glb},
        overview_lod="lod0",
        thumbnail=thumbnail,
        textures=[texture],
    ).manifest
    glb_path = tmp_path / "lod0.glb"
    thumbnail_path = tmp_path / "thumbnail.webp"
    texture_path = tmp_path / "texture.png"
    glb_path.write_bytes(glb_data)
    thumbnail_path.write_bytes(thumbnail.data)
    texture_path.write_bytes(texture_data)
    return dict(bundle), {
        glb.sha256: glb_path,
        str(thumbnail.manifest["sha256"]): thumbnail_path,
        texture["sha256"]: texture_path,
    }


def _assert_ccw(points: list[dict[str, float]]) -> None:
    area = 0.5 * sum(
        points[index]["x"] * points[(index + 1) % len(points)]["z"]
        - points[(index + 1) % len(points)]["x"] * points[index]["z"]
        for index in range(len(points))
    )
    assert area > 0


def test_real_p0_glbs_have_exact_expected_identity_and_finite_geometry():
    paths = _require_real_p0()
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    expected = {
        record["assetId"]: {
            item["kind"]: item for item in record["artifacts"]
        }
        for record in evidence["assets"]
    }
    cases = (
        ("asset-cnc-vmc-f26678cafa91", paths["cnc"]["glb"]),
        ("asset-wa01-e773742615b2", paths["workstation"]["glb"]),
    )
    for asset_id, path in cases:
        artifact = expected[asset_id]["glb"]
        inspection = inspect_glb(
            path,
            expected_sha256=artifact["sha256"],
            expected_byte_length=artifact["byteLength"],
        )
        assert inspection.sha256 == artifact["sha256"]
        assert inspection.byte_length == artifact["byteLength"]
        assert inspection.declared_byte_length == inspection.byte_length
        assert inspection.mesh_count > 0
        assert inspection.primitive_count > 0
        assert inspection.position_vertex_count > 0
        assert inspection.scene_triangle_count > 0
        assert len(inspection.json_chunk_sha256) == 64
        assert len(inspection.binary_chunk_sha256) == 64
        for endpoint in ("minimum", "maximum"):
            assert all(
                math.isfinite(inspection.aabb[endpoint][axis])
                for axis in ("x", "y", "z")
            )


def test_glb_inspection_applies_scene_transforms_to_bounds():
    inspection = inspect_glb(_minimal_glb(translation=(4.0, 5.0, 6.0)))
    assert inspection.aabb == {
        "minimum": {"x": 4.0, "y": 5.0, "z": 6.0},
        "maximum": {"x": 5.0, "y": 6.0, "z": 7.0},
    }


def test_aabb_proxy_glb_is_deterministic_lightweight_and_preserves_bounds():
    bounds = {
        "minimum": {"x": -2.5, "y": 0.0, "z": -1.25},
        "maximum": {"x": 2.5, "y": 4.75, "z": 1.25},
    }
    first = build_aabb_proxy_glb(bounds)
    second = build_aabb_proxy_glb(bounds)
    assert first == second
    assert len(first) < 2048

    inspection = inspect_glb(first)
    assert inspection.aabb == bounds
    assert inspection.scene_triangle_count == 12
    assert inspection.position_vertex_count == 8


@pytest.mark.parametrize(
    "bounds",
    [
        {
            "minimum": {"x": 0, "y": 0, "z": 0},
            "maximum": {"x": 0, "y": 1, "z": 1},
        },
        {
            "minimum": {"x": 0, "y": 0, "z": 0},
            "maximum": {"x": float("nan"), "y": 1, "z": 1},
        },
    ],
)
def test_aabb_proxy_glb_rejects_degenerate_or_nonfinite_bounds(bounds):
    with pytest.raises(ArtifactValidationError):
        build_aabb_proxy_glb(bounds)


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda data: b"BAD!" + data[4:], "glb_magic_invalid"),
        (
            lambda data: data[:8]
            + struct.pack("<I", len(data) + 4)
            + data[12:],
            "glb_length_mismatch",
        ),
    ],
)
def test_glb_structure_fails_closed(mutator, code):
    with pytest.raises(ArtifactValidationError) as exc_info:
        inspect_glb(mutator(_minimal_glb()))
    assert exc_info.value.code == code


def test_glb_exact_hash_and_vertex_bounds_fail_closed():
    data = _minimal_glb()
    with pytest.raises(ArtifactValidationError) as hash_error:
        inspect_glb(data, expected_sha256="0" * 64)
    assert hash_error.value.code == "glb_sha256_mismatch"

    mismatched = _minimal_glb(declared_maximum=(2.0, 2.0, 2.0))
    with pytest.raises(ArtifactValidationError) as bounds_error:
        inspect_glb(mismatched)
    assert bounds_error.value.code == "glb_position_bounds_mismatch"


def test_nonfinite_vertex_bytes_are_rejected():
    data = _minimal_glb(
        positions=((0.0, 0.0, 0.0), (1.0, float("nan"), 0.0), (0.0, 1.0, 1.0)),
        declared_minimum=(0.0, 0.0, 0.0),
        declared_maximum=(1.0, 1.0, 1.0),
    )
    with pytest.raises(ArtifactValidationError) as exc_info:
        inspect_glb(data)
    assert exc_info.value.code == "glb_position_nonfinite"


def test_real_extractor_bounds_derive_review_required_canonical_candidates():
    paths = _require_real_p0()
    for record in paths.values():
        extracted = json.loads(record["extracted"].read_text(encoding="utf-8-sig"))
        reviewed = json.loads(record["normalized"].read_text(encoding="utf-8"))
        candidates = derive_geometry_candidates(
            extracted["physical"]["boundingBox"],
            evidence_refs=["ev-cad-extraction"],
        )
        assert candidates["authorityBoundary"] == {
            "placementGeometryOnly": True,
            "safetyAuthority": False,
            "clearanceAuthority": False,
            "floorLoadAuthority": False,
        }
        assert (
            candidates["canonicalAabbCandidate"]["value"]
            == reviewed["geometry"]["aabb"]
        )
        assert candidates["floorAnchorCandidate"]["value"] == {
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
        }
        assert candidates["floorAnchorCandidate"]["claimStatus"] == "candidate"
        assert candidates["floorAnchorCandidate"]["evidenceStatus"] == "inferred"
        assert candidates["floorAnchorCandidate"]["verified"] is False
        footprint = candidates["footprintCandidate"]["value"]
        _assert_ccw(footprint)
        assert candidates["collisionProxyCandidate"]["model"] == "compound_box"
        assert (
            candidates["collisionProxyCandidate"]["authorityBoundary"]
            if "authorityBoundary" in candidates["collisionProxyCandidate"]
            else candidates["authorityBoundary"]["safetyAuthority"]
        ) is False
        for key, value in candidates.items():
            if key.endswith("Candidate"):
                assert value["requiresReview"] is True
                assert value["verified"] is False


def test_geometry_candidate_rejects_non_si_nonfinite_and_degenerate_bounds():
    valid = {
        "minX": 0.0,
        "minY": 0.0,
        "minZ": 0.0,
        "maxX": 1.0,
        "maxY": 2.0,
        "maxZ": 3.0,
    }
    with pytest.raises(ArtifactValidationError) as unit_error:
        derive_geometry_candidates(
            valid,
            evidence_refs=["ev-1"],
            source_coordinate_units="mm",
        )
    assert unit_error.value.code == "extractor_units_not_si"

    nonfinite = dict(valid, maxZ=float("inf"))
    with pytest.raises(ArtifactValidationError) as finite_error:
        derive_geometry_candidates(nonfinite, evidence_refs=["ev-1"])
    assert finite_error.value.code == "extractor_bounds_invalid"

    degenerate = dict(valid, maxX=0.0)
    with pytest.raises(ArtifactValidationError) as degenerate_error:
        derive_geometry_candidates(degenerate, evidence_refs=["ev-1"])
    assert degenerate_error.value.code == "extractor_bounds_degenerate"


def test_real_disguised_bmp_is_detected_and_transcoded_to_nonblank_webp():
    paths = _require_real_p0()
    source = paths["cnc"]["image"]
    assert source.suffix.lower() == ".png"
    assert detect_image_format(source.read_bytes()) == "BMP"
    artifact = normalize_web_image(source, output_format="WEBP")
    assert artifact.data[:4] == b"RIFF"
    assert artifact.data[8:12] == b"WEBP"
    assert artifact.manifest["mediaType"] == "image/webp"
    assert artifact.manifest["validation"]["nonblank"] is True
    assert artifact.manifest["sourceInspection"]["detectedFormat"] == "BMP"
    assert artifact.manifest["findings"][0]["code"] == "image_extension_mismatch"
    assert artifact.manifest["byteLength"] < source.stat().st_size


def test_image_normalization_is_deterministic_and_can_emit_real_png():
    source = _nonblank_png_bytes()
    first = normalize_web_image(source, output_format="PNG", claimed_suffix=".png")
    second = normalize_web_image(source, output_format="PNG", claimed_suffix=".png")
    assert first.data == second.data
    assert first.manifest == second.manifest
    assert first.data.startswith(b"\x89PNG\r\n\x1a\n")
    assert first.manifest["findings"] == []


def test_blank_corrupt_and_oversized_images_fail_closed():
    blank = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(blank, format="PNG")
    with pytest.raises(ArtifactValidationError) as blank_error:
        normalize_web_image(blank.getvalue())
    assert blank_error.value.code == "image_blank"

    with pytest.raises(ArtifactValidationError) as corrupt_error:
        normalize_web_image(b"not-an-image")
    assert corrupt_error.value.code == "image_format_unsupported"

    with pytest.raises(ArtifactValidationError) as byte_error:
        normalize_web_image(_nonblank_png_bytes(), maximum_input_bytes=8)
    assert byte_error.value.code == "image_oversized"

    with pytest.raises(ArtifactValidationError) as pixel_error:
        normalize_web_image(_nonblank_png_bytes(), maximum_pixels=100)
    assert pixel_error.value.code == "image_dimensions_oversized"


def test_lod_validation_enforces_bounds_order_and_budgets():
    lod0 = inspect_glb(_minimal_glb())
    lod1 = replace(
        lod0,
        sha256="1" * 64,
        byte_length=max(1, lod0.byte_length - 1),
        triangle_count=0,
        scene_triangle_count=0,
    )
    result = validate_lod_set(
        {"lod0": lod0, "lod1": lod1},
        overview_lod="lod1",
    )
    assert result["boundsConsistent"] is True
    assert result["budgets"]["withinBudget"] is True

    inconsistent = replace(
        lod1,
        sha256="2" * 64,
        aabb={
            "minimum": {"x": 10.0, "y": 0.0, "z": 0.0},
            "maximum": {"x": 11.0, "y": 1.0, "z": 1.0},
        },
    )
    with pytest.raises(ArtifactValidationError) as bounds_error:
        validate_lod_set(
            {"lod0": lod0, "lod1": inconsistent},
            overview_lod="lod1",
        )
    assert bounds_error.value.code == "lod_bounds_inconsistent"

    too_complex = replace(lod1, sha256="3" * 64, scene_triangle_count=150_001)
    with pytest.raises(ArtifactValidationError) as triangle_error:
        validate_lod_set(
            {"lod0": replace(lod0, scene_triangle_count=200_000), "lod1": too_complex},
            overview_lod="lod1",
        )
    assert triangle_error.value.code == "lod_overview_triangle_budget_exceeded"

    too_large = replace(
        lod1,
        sha256="4" * 64,
        byte_length=10 * 1024 * 1024 + 1,
    )
    with pytest.raises(ArtifactValidationError) as byte_error:
        validate_lod_set(
            {"lod0": replace(lod0, byte_length=11 * 1024 * 1024), "lod1": too_large},
            overview_lod="lod1",
        )
    assert byte_error.value.code == "lod_overview_byte_budget_exceeded"


def test_render_bundle_manifest_is_canonical_and_revision_is_separate():
    glb = inspect_glb(_minimal_glb())
    thumbnail = normalize_web_image(_nonblank_png_bytes())
    first = build_render_bundle_manifest(
        asset_id="asset-test",
        geometry_interface_revision=GEOMETRY_INTERFACE_REVISION,
        lods={"lod0": glb},
        overview_lod="lod0",
        thumbnail=thumbnail,
    )
    second = build_render_bundle_manifest(
        asset_id="asset-test",
        geometry_interface_revision=GEOMETRY_INTERFACE_REVISION,
        lods={"lod0": glb},
        overview_lod="lod0",
        thumbnail=thumbnail,
    )
    assert first == second
    assert len(first.render_bundle_revision) == 64
    assert "renderBundleRevision" not in first.manifest
    assert "assetDefinitionRevision" not in first.manifest
    encoded = canonical_json_bytes(first.manifest)
    encoded.decode("ascii")
    assert json.loads(encoded)["readiness"]["visualReady"] is True

    alternate_thumbnail = normalize_web_image(
        _nonblank_png_bytes(),
        output_format="PNG",
    )
    changed = build_render_bundle_manifest(
        asset_id="asset-test",
        geometry_interface_revision=GEOMETRY_INTERFACE_REVISION,
        lods={"lod0": glb},
        overview_lod="lod0",
        thumbnail=alternate_thumbnail,
    )
    assert changed.render_bundle_revision != first.render_bundle_revision
    assert (
        changed.manifest["geometryInterfaceRevision"]
        == first.manifest["geometryInterfaceRevision"]
    )


def test_render_bundle_rejects_unvalidated_thumbnail():
    glb = inspect_glb(_minimal_glb())
    thumbnail = normalize_web_image(_nonblank_png_bytes())
    invalid = replace(
        thumbnail,
        manifest={
            **thumbnail.manifest,
            "validation": {
                "decoded": True,
                "nonblank": False,
                "magicMatchesMediaType": True,
            },
        },
    )
    with pytest.raises(ArtifactValidationError) as exc_info:
        build_render_bundle_manifest(
            asset_id="asset-test",
            geometry_interface_revision=GEOMETRY_INTERFACE_REVISION,
            lods={"lod0": glb},
            overview_lod="lod0",
            thumbnail=invalid,
        )
    assert exc_info.value.code == "thumbnail_invalid"


def test_publication_artifact_sources_return_deterministic_sha_copy_descriptors(
    tmp_path,
):
    bundle, sources = _synthetic_render_bundle_sources(tmp_path)
    first = validate_render_artifact_sources(bundle, sources)
    second = validate_render_artifact_sources(bundle, sources)

    assert first == second
    assert list(first) == sorted(first)
    assert set(first) == set(sources)
    for digest, descriptor in first.items():
        assert descriptor["sourcePath"] == sources[digest]
        assert descriptor["byteLength"] == sources[digest].stat().st_size
        assert descriptor["mediaType"] in {
            "model/gltf-binary",
            "image/png",
            "image/webp",
        }
        assert descriptor["kind"] in {"lod", "thumbnail", "texture"}
        assert descriptor["artifactIds"]
        assert descriptor["inspection"]


def test_publication_artifact_sources_reject_fabricated_hashes(tmp_path):
    bundle, sources = _synthetic_render_bundle_sources(tmp_path)
    fabricated = "f" * 64
    lod = bundle["lodArtifacts"][0]
    real_digest = lod["sha256"]
    lod["sha256"] = fabricated
    bundle["overviewGeometry"]["sha256"] = fabricated
    sources[fabricated] = sources.pop(real_digest)

    with pytest.raises(ArtifactValidationError) as exc_info:
        validate_render_artifact_sources(bundle, sources)
    assert exc_info.value.code == "glb_sha256_mismatch"


def test_publication_artifact_sources_reject_missing_and_unclaimed_files(
    tmp_path,
):
    bundle, sources = _synthetic_render_bundle_sources(tmp_path)
    missing_sources = dict(sources)
    missing_sources.pop(bundle["thumbnail"]["sha256"])
    with pytest.raises(ArtifactValidationError) as missing_error:
        validate_render_artifact_sources(bundle, missing_sources)
    assert missing_error.value.code == "staged_artifact_missing"

    missing_file_sources = dict(sources)
    missing_file_sources[bundle["thumbnail"]["sha256"]] = (
        tmp_path / "missing-thumbnail.webp"
    )
    with pytest.raises(ArtifactValidationError) as missing_file_error:
        validate_render_artifact_sources(bundle, missing_file_sources)
    assert missing_file_error.value.code == "render_image_unreadable"

    extra_data = b"checkpointed-but-unclaimed"
    extra_path = tmp_path / "extra.bin"
    extra_path.write_bytes(extra_data)
    extra_sources = {
        **sources,
        _sha256(extra_data): extra_path,
    }
    with pytest.raises(ArtifactValidationError) as extra_error:
        validate_render_artifact_sources(bundle, extra_sources)
    assert extra_error.value.code == "staged_artifact_unclaimed"


def test_publication_artifact_sources_reject_corrupt_glb_and_image(tmp_path):
    bundle, sources = _synthetic_render_bundle_sources(tmp_path)
    corrupt_glb = b"BAD!" + b"\x00" * 28
    corrupt_glb_digest = _sha256(corrupt_glb)
    glb_record = bundle["lodArtifacts"][0]
    real_glb_digest = glb_record["sha256"]
    glb_record["sha256"] = corrupt_glb_digest
    glb_record["byteLength"] = len(corrupt_glb)
    bundle["overviewGeometry"]["sha256"] = corrupt_glb_digest
    corrupt_glb_path = tmp_path / "corrupt.glb"
    corrupt_glb_path.write_bytes(corrupt_glb)
    corrupt_glb_sources = dict(sources)
    corrupt_glb_sources.pop(real_glb_digest)
    corrupt_glb_sources[corrupt_glb_digest] = corrupt_glb_path
    with pytest.raises(ArtifactValidationError) as glb_error:
        validate_render_artifact_sources(bundle, corrupt_glb_sources)
    assert glb_error.value.code == "glb_magic_invalid"

    bundle, sources = _synthetic_render_bundle_sources(tmp_path / "image-case")
    corrupt_image = b"RIFF" + struct.pack("<I", 24) + b"WEBPnot-decodable"
    corrupt_image_digest = _sha256(corrupt_image)
    thumbnail_record = bundle["thumbnail"]
    real_image_digest = thumbnail_record["sha256"]
    thumbnail_record["sha256"] = corrupt_image_digest
    thumbnail_record["byteLength"] = len(corrupt_image)
    corrupt_image_path = tmp_path / "corrupt.png"
    corrupt_image_path.write_bytes(corrupt_image)
    corrupt_image_sources = dict(sources)
    corrupt_image_sources.pop(real_image_digest)
    corrupt_image_sources[corrupt_image_digest] = corrupt_image_path
    with pytest.raises(ArtifactValidationError) as image_error:
        validate_render_artifact_sources(bundle, corrupt_image_sources)
    assert image_error.value.code == "render_image_corrupt"


def test_publication_artifact_sources_reject_wrong_bytes_and_claims(tmp_path):
    bundle, sources = _synthetic_render_bundle_sources(tmp_path)
    thumbnail_digest = bundle["thumbnail"]["sha256"]
    wrong_bytes = bytearray(sources[thumbnail_digest].read_bytes())
    wrong_bytes[-1] ^= 1
    wrong_path = tmp_path / "wrong.webp"
    wrong_path.write_bytes(wrong_bytes)
    wrong_sources = {**sources, thumbnail_digest: wrong_path}
    with pytest.raises(ArtifactValidationError) as identity_error:
        validate_render_artifact_sources(bundle, wrong_sources)
    assert identity_error.value.code == "render_image_sha256_mismatch"

    bundle, sources = _synthetic_render_bundle_sources(tmp_path / "claim-case")
    bundle["thumbnail"]["width"] += 1
    with pytest.raises(ArtifactValidationError) as claim_error:
        validate_render_artifact_sources(bundle, sources)
    assert claim_error.value.code == "render_artifact_claim_mismatch"


def test_real_p0_artifact_sources_pass_publication_revalidation(tmp_path):
    paths = _require_real_p0()
    glb = inspect_glb(paths["cnc"]["glb"])
    thumbnail = normalize_web_image(paths["cnc"]["image"])
    thumbnail_path = tmp_path / "thumbnail.webp"
    thumbnail_path.write_bytes(thumbnail.data)
    bundle = build_render_bundle_manifest(
        asset_id="asset-cnc-publication-test",
        geometry_interface_revision=GEOMETRY_INTERFACE_REVISION,
        lods={"lod0": glb},
        overview_lod="lod0",
        thumbnail=thumbnail,
    ).manifest
    sources = {
        glb.sha256: paths["cnc"]["glb"],
        str(thumbnail.manifest["sha256"]): thumbnail_path,
    }

    descriptors = validate_render_artifact_sources(bundle, sources)
    assert descriptors[glb.sha256]["kind"] == "lod"
    assert descriptors[glb.sha256]["inspection"]["sceneTriangleCount"] > 0
    assert descriptors[thumbnail.manifest["sha256"]]["kind"] == "thumbnail"
    assert descriptors[thumbnail.manifest["sha256"]]["inspection"]["nonblank"] is True
