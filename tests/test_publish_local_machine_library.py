import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image
import pytest

from ai_inspector.industrial_assets.artifacts import build_aabb_proxy_glb


ROOT = Path(__file__).resolve().parents[1]


def _load_tool(name: str):
    path = ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PUBLISHER = _load_tool("publish_local_machine_library")
SOFTWARE_RENDERER = _load_tool(
    "render_industrial_asset_software_thumbnail"
)


def _entry(asset_id: str, digest: str, name: str = "Asset") -> dict:
    return {
        "assetId": asset_id,
        "category": "Machines",
        "displayName": name,
        "source": {"sha256": digest},
    }


def test_catalog_merge_preserves_existing_and_replaces_matching_identity():
    existing = [
        _entry("asset-a", "a" * 64, "Original A"),
        _entry("asset-b", "b" * 64, "Asset B"),
    ]
    published = [
        _entry("asset-a", "c" * 64, "Updated A"),
        _entry("asset-c", "d" * 64, "Asset C"),
    ]

    merged = PUBLISHER._merge_catalog_assets(existing, published)

    assert {item["assetId"] for item in merged} == {
        "asset-a",
        "asset-b",
        "asset-c",
    }
    assert next(
        item for item in merged if item["assetId"] == "asset-a"
    )["displayName"] == "Updated A"


def test_missing_source_filter_skips_unchanged_and_duplicate_bytes(tmp_path):
    first = tmp_path / "first.sldprt"
    duplicate = tmp_path / "duplicate.sldprt"
    changed = tmp_path / "changed.sldprt"
    first.write_bytes(b"same")
    duplicate.write_bytes(b"same")
    changed.write_bytes(b"new")
    digest = PUBLISHER._sha256(first)
    existing = [_entry("asset-first", digest)]
    sources = (
        PUBLISHER.SourceAsset(
            "asset-first", "First", "Machines", first.name, "part", ""
        ),
        PUBLISHER.SourceAsset(
            "asset-duplicate",
            "Duplicate",
            "Machines",
            duplicate.name,
            "part",
            "",
        ),
        PUBLISHER.SourceAsset(
            "asset-changed", "Changed", "Machines", changed.name, "part", ""
        ),
    )

    missing, skipped = PUBLISHER._missing_sources(
        sources,
        source_root=tmp_path,
        existing=existing,
    )

    assert [source.asset_id for source in missing] == ["asset-changed"]
    assert skipped == [
        {"assetId": "asset-first", "reason": "unchanged_asset"},
        {
            "assetId": "asset-duplicate",
            "existingAssetId": "asset-first",
            "reason": "duplicate_source",
        },
    ]


def test_manifest_assets_are_curated_relative_and_type_checked(tmp_path):
    manifest = tmp_path / "assets.json"
    manifest.write_text(json.dumps({
        "schemaVersion": 1,
        "assets": [{
            "assetId": "asset-test-crane",
            "displayName": "Test Crane",
            "category": "Material Handling",
            "relativePath": "crane/Test Crane.SLDASM",
            "sourceKind": "assembly",
            "description": "Curated crane assembly.",
            "tags": ["crane", "lifting"],
            "canonicalRotationDegrees": {"x": -90, "z": 0},
            "supportSurfaces": [{
                "surfaceId": "work-deck",
                "label": "Work deck",
                "elevationRatio": 0.8,
                "originXRatio": -0.1,
                "originZRatio": 0.2,
                "widthRatio": 0.75,
                "depthRatio": 0.6,
                "allowedSides": ["above", "below"],
                "evidenceStatus": "derived",
            }],
        }],
    }), encoding="utf-8")

    assets = PUBLISHER._manifest_assets(manifest)

    assert assets == (
        PUBLISHER.SourceAsset(
            "asset-test-crane",
            "Test Crane",
            "Material Handling",
            str(Path("crane") / "Test Crane.SLDASM"),
            "assembly",
            "Curated crane assembly.",
            ("crane", "lifting"),
            (-90.0, 0.0, 0.0),
            ({
                "surfaceId": "work-deck",
                "label": "Work deck",
                "elevationRatio": 0.8,
                "originXRatio": -0.1,
                "originZRatio": 0.2,
                "widthRatio": 0.75,
                "depthRatio": 0.6,
                "allowedSides": ("above", "below"),
                "evidenceStatus": "derived",
            },),
        ),
    )


def test_manifest_rejects_invalid_support_surface(tmp_path):
    manifest = tmp_path / "assets.json"
    base = {
        "schemaVersion": 1,
        "assets": [{
            "assetId": "asset-test-bench",
            "displayName": "Test Bench",
            "category": "Workstations",
            "relativePath": "bench.sldprt",
            "sourceKind": "part",
            "description": "Test bench.",
            "supportSurfaces": [{
                "surfaceId": "worktop",
                "label": "Worktop",
                "widthRatio": 1.25,
            }],
        }],
    }
    manifest.write_text(json.dumps(base), encoding="utf-8")

    with pytest.raises(ValueError, match="widthRatio must be between"):
        PUBLISHER._manifest_assets(manifest)


def test_manifest_rejects_support_surface_origin_outside_asset_ratio(tmp_path):
    manifest = tmp_path / "assets.json"
    manifest.write_text(json.dumps({
        "schemaVersion": 1,
        "assets": [{
            "assetId": "asset-test-bench",
            "displayName": "Test Bench",
            "category": "Workstations",
            "relativePath": "bench.sldprt",
            "sourceKind": "part",
            "description": "Test bench.",
            "supportSurfaces": [{
                "surfaceId": "worktop",
                "label": "Worktop",
                "originZRatio": 1.25,
            }],
        }],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="originZRatio must be between"):
        PUBLISHER._manifest_assets(manifest)


def test_forced_catalog_only_publish_reuses_current_glb(tmp_path, monkeypatch):
    source_path = tmp_path / "bench.sldprt"
    source_path.write_bytes(b"cad")
    output_root = tmp_path / "published"
    target = output_root / "test-bench"
    target.mkdir(parents=True)
    glb_path = target / "bench_colored.glb"
    glb_path.write_bytes(b"glb")
    source = PUBLISHER.SourceAsset(
        "asset-test-bench",
        "Test Bench",
        "Workstations",
        source_path.name,
        "part",
        "Test bench.",
    )
    cache_calls = []

    def current_cached_glb(candidate_target, candidate_source):
        cache_calls.append((candidate_target, candidate_source))
        return glb_path

    monkeypatch.setattr(PUBLISHER, "_current_cached_glb", current_cached_glb)
    monkeypatch.setattr(
        PUBLISHER,
        "_catalog_entry",
        lambda *_args: {
            "assetId": source.asset_id,
            "dimensions": {"width": 1.0, "depth": 1.0, "height": 1.0},
        },
    )

    entries, failures = PUBLISHER.publish(
        (source,),
        source_root=tmp_path,
        output_root=output_root,
        extractor=tmp_path / "unused.exe",
        force=True,
        catalog_only=True,
        start_solidworks=False,
    )

    assert failures == []
    assert entries[0]["assetId"] == source.asset_id
    assert cache_calls == [(target, source_path)]


def test_manifest_rejects_invalid_canonical_rotation(tmp_path):
    manifest = tmp_path / "assets.json"
    base = {
        "schemaVersion": 1,
        "assets": [{
            "assetId": "asset-test-machine",
            "displayName": "Test Machine",
            "category": "Machines",
            "relativePath": "machine.sldprt",
            "sourceKind": "part",
            "description": "Test machine.",
            "tags": [],
        }],
    }
    base["assets"][0]["canonicalRotationDegrees"] = {"up": 90}
    manifest.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="contains unknown fields"):
        PUBLISHER._manifest_assets(manifest)

    base["assets"][0]["canonicalRotationDegrees"] = {"x": True}
    manifest.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a finite number"):
        PUBLISHER._manifest_assets(manifest)


def test_canonical_rotation_uses_threejs_column_major_xyz_order():
    matrix = PUBLISHER._rotation_matrix_xyz_degrees((-90.0, 0.0, 0.0))

    def transform(point):
        x, y, z = point
        return (
            matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
            matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
            matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
        )

    assert transform((0.0, 1.0, 0.0)) == pytest.approx((0.0, 0.0, -1.0))
    assert transform((0.0, 0.0, 1.0)) == pytest.approx((0.0, 1.0, 0.0))


def test_orientation_change_republishes_unchanged_cad_source(tmp_path):
    source_path = tmp_path / "machine.sldprt"
    source_path.write_bytes(b"same-cad")
    digest = PUBLISHER._sha256(source_path)
    source = PUBLISHER.SourceAsset(
        "asset-machine",
        "Machine",
        "Machines",
        source_path.name,
        "part",
        "Machine.",
        canonical_rotation_degrees=(-90.0, 0.0, 0.0),
    )
    existing = [{
        **_entry("asset-machine", digest),
        "canonicalOrientation": {
            "rotationDegrees": {"x": 0, "y": 0, "z": 0},
        },
    }]

    missing, skipped = PUBLISHER._missing_sources(
        (source,), source_root=tmp_path, existing=existing
    )

    assert missing == (source,)
    assert skipped == []


def test_manifest_rejects_duplicate_paths_and_kind_mismatch(tmp_path):
    manifest = tmp_path / "assets.json"
    base = {
        "displayName": "Asset",
        "category": "Machines",
        "description": "Asset description.",
        "tags": [],
    }
    manifest.write_text(json.dumps({
        "schemaVersion": 1,
        "assets": [
            {
                **base,
                "assetId": "asset-first",
                "relativePath": "machine.sldprt",
                "sourceKind": "part",
            },
            {
                **base,
                "assetId": "asset-second",
                "relativePath": "MACHINE.SLDPRT",
                "sourceKind": "part",
            },
        ],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate asset manifest path"):
        PUBLISHER._manifest_assets(manifest)

    manifest.write_text(json.dumps({
        "schemaVersion": 1,
        "assets": [{
            **base,
            "assetId": "asset-wrong-kind",
            "relativePath": "machine.sldprt",
            "sourceKind": "assembly",
        }],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match sourceKind"):
        PUBLISHER._manifest_assets(manifest)


def test_close_new_solidworks_instances_only_terminates_created_pids(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        PUBLISHER,
        "_windows_process_ids",
        lambda _name: {10, 20, 30},
    )

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(PUBLISHER.subprocess, "run", fake_run)

    closed = PUBLISHER._close_new_solidworks_instances({10, 30})

    assert closed == (20,)
    assert calls == [["taskkill", "/PID", "20", "/T", "/F"]]


def test_part_extraction_falls_back_to_body_glb_after_timeout(
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "dense.sldprt"
    source_path.write_bytes(b"cad")
    target = tmp_path / "output"
    target.mkdir()
    calls = []

    def fake_attempt(command, **_kwargs):
        calls.append(command)
        if "--part-glb" in command:
            raise subprocess.TimeoutExpired(command, 300, "partial", "")
        (target / "dense_body.glb").write_bytes(b"glb")
        return subprocess.CompletedProcess(command, 0, "body", "")

    monkeypatch.setattr(PUBLISHER, "_run_extraction_attempt", fake_attempt)
    source = PUBLISHER.SourceAsset(
        "asset-dense",
        "Dense",
        "Machines",
        source_path.name,
        "part",
        "Dense test part.",
    )

    result = PUBLISHER._extract(
        source,
        source_path,
        target,
        tmp_path / "extractor.exe",
        start_solidworks=True,
    )

    assert result.name == "dense_body.glb"
    assert "--part-glb" in calls[0]
    assert "--process-bodies" in calls[1]
    assert "--part-glb" not in calls[1]
    assert len(calls) == 2
    log = (target / "extractor.log").read_text(encoding="utf-8")
    assert "custom export timed out" in log
    assert "body export" in log


def test_software_thumbnail_is_nonblank_bounded_and_repeatable(tmp_path):
    source = tmp_path / "box.glb"
    source.write_bytes(build_aabb_proxy_glb({
        "minimum": {"x": -1.0, "y": 0.0, "z": -0.5},
        "maximum": {"x": 1.0, "y": 1.5, "z": 0.5},
    }))
    outputs = []
    evidence_records = []
    for index in range(2):
        output = tmp_path / f"box-{index}.webp"
        evidence = tmp_path / f"box-{index}.json"
        outputs.append(output)
        evidence_records.append(
            SOFTWARE_RENDERER.render_software_thumbnail(
                source,
                output,
                evidence_path=evidence,
                width=320,
                height=200,
            )
        )
        assert json.loads(evidence.read_text(encoding="ascii")) == evidence_records[-1]

    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    assert evidence_records[0]["passed"] is True
    assert evidence_records[0]["geometry"]["triangleCount"] == 12
    assert evidence_records[0]["output"]["pixelValidation"]["nonblank"] is True
    with Image.open(outputs[0]) as image:
        image.load()
        assert image.format == "WEBP"
        assert image.size == (320, 200)


def test_software_thumbnail_applies_canonical_source_transform(tmp_path):
    source = tmp_path / "z-up.glb"
    source.write_bytes(build_aabb_proxy_glb({
        "minimum": {"x": -1.0, "y": -3.0, "z": 0.0},
        "maximum": {"x": 1.0, "y": 3.0, "z": 1.0},
    }))
    output = tmp_path / "upright.webp"
    rotate_x_negative_90 = PUBLISHER._rotation_matrix_xyz_degrees(
        (-90.0, 0.0, 0.0)
    )

    evidence = SOFTWARE_RENDERER.render_software_thumbnail(
        source,
        output,
        width=320,
        height=200,
        source_transform=rotate_x_negative_90,
    )

    assert evidence["geometry"]["bounds"]["size"] == pytest.approx(
        [2.0, 1.0, 6.0]
    )
    assert evidence["renderer"]["sourceTransform"] == pytest.approx(
        rotate_x_negative_90
    )
