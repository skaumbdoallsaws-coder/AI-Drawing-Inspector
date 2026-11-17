"""Real isolated MB3 worker parity and input/output tampering; run sequentially."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from ai_inspector.industrial_assets import model_builder_runner as host
from tests.model_builder_test_support import module, recipe, reference
from tests.model_builder_composition_support import CatalogFixture, credit, cube_payload, triangle_glb
from tests.test_model_builder_composition import cage_tag, printed_payload

DEPENDENCIES = Path(np.__file__).resolve().parent.parent


def job(tmp_path, kind="pallet"):
    fixtures = CatalogFixture(tmp_path)
    if kind == "cage":
        raw, _ = cage_tag(fixtures)
    else:
        if kind == "pallet":
            built = module("build").build_model(reference("pallet-plain"))
            payload, size = built.glb, built.dimensions
        elif kind == "print":
            built = printed_payload()
            payload, size = built.glb, built.dimensions
        else:
            payload, size = cube_payload(), {"width": 1, "height": 1, "depth": 1}
        asset = fixtures.add(kind, payload, dimensions=size, attribution=credit() if kind == "credit" else None)
        entry, _ = fixtures.include(asset)
        raw = recipe(entry, size=size)
    directory = tmp_path / "job"
    directory.mkdir()
    normalized = host.write_job_inputs(directory, raw, categories=[raw["category"]], appearance_ids=[], include_catalog=fixtures.catalog)
    return directory, normalized, fixtures


@pytest.mark.parametrize("kind", ["pallet", "cage", "print", "credit"])
def test_worker_bytes_equal_in_process_includes_and_second_worker(tmp_path, kind):
    directory, raw, fixtures = job(tmp_path, kind)
    built = fixtures.build(raw)
    before = {p.name: p.read_bytes() for p in (directory / "includes").iterdir()}
    result = host.run_build(directory, DEPENDENCIES)
    assert (directory / "model.glb").read_bytes() == built.glb
    assert result["includes"] == built.includes and result["attribution"] == built.attribution
    assert result["partMap"] == built.part_map
    assert {p.name: p.read_bytes() for p in (directory / "includes").iterdir()} == before
    second = tmp_path / "second"
    second.mkdir()
    host.write_job_inputs(second, raw, categories=[raw["category"]], appearance_ids=[], include_catalog=fixtures.catalog)
    host.run_build(second, DEPENDENCIES)
    assert (second / "model.glb").read_bytes() == built.glb


def test_copied_include_hash_refusal_is_decoded_and_inputs_survive(tmp_path):
    directory, _, _ = job(tmp_path)
    target = directory / "includes/0.glb"
    payload = bytearray(target.read_bytes())
    payload[-1] ^= 1
    target.write_bytes(payload)
    with pytest.raises(host.ModelBuildError) as caught:
        host.run_build(directory, DEPENDENCIES)
    assert caught.value.code == "include_mismatch" and caught.value.path == "$.entries[0].artifactSha256"
    assert target.read_bytes() == payload
    assert not any((directory / name).exists() for name in host.job_io.OUTPUT_NAMES)


def test_heavy_include_is_refused_in_worker_before_geometry(tmp_path):
    from hashlib import sha256
    directory, raw, _ = job(tmp_path)
    payload = triangle_glb(triangles=60001)
    raw["entries"][0]["artifactSha256"] = sha256(payload).hexdigest()
    manifest = json.loads((directory / "includes/manifest.json").read_bytes())
    manifest[0]["artifactSha256"] = sha256(payload).hexdigest()
    (directory / "recipe.json").write_bytes(host.json_bytes(raw))
    (directory / "includes/manifest.json").write_bytes(host.json_bytes(manifest))
    (directory / "includes/0.glb").write_bytes(payload)
    with pytest.raises(host.ModelBuildError) as caught:
        host.run_build(directory, DEPENDENCIES)
    assert caught.value.code == "budget_exceeded" and caught.value.triangles == 60001
    assert caught.value.path == "$.entries[0]"


@pytest.mark.parametrize("tamper", ["manifest", "mapping", "frame", "anchor", "credit", "budget"])
def test_host_binds_composition_metadata_to_pinned_inputs(tmp_path, monkeypatch, tamper):
    directory, _, _ = job(tmp_path)
    launch = host.launch._launch
    def changed(*args, **kwargs):
        launch(*args, **kwargs)
        if tamper == "manifest":
            target = directory / "includes/manifest.json"
            value = json.loads(target.read_bytes())
            value[0]["hasSurfaces"] = not value[0]["hasSurfaces"]
        else:
            target = directory / "result.json"
            value = json.loads(target.read_bytes())
            if tamper == "mapping":
                value["includes"][0]["partMap"] = {}
            elif tamper == "frame":
                value["includes"][0]["frame"]["translation"][0] += .01
            elif tamper == "anchor":
                value["includes"][0]["anchorable"] = False
            elif tamper == "credit":
                value["attribution"] = credit()
            else:
                value["budgets"]["triangles"] += 1
        target.write_bytes(host.json_bytes(value))
    monkeypatch.setattr(host.launch, "_launch", changed)
    monkeypatch.setattr(host.primitives, "verify", lambda *a, **k: pytest.fail("tampered include reached verifier"))
    with pytest.raises(host.ModelImportError) as caught:
        host.run_build(directory, DEPENDENCIES)
    assert caught.value.code == "model_worker_failed"
    assert not any((directory / name).exists() for name in host.job_io.OUTPUT_NAMES)
