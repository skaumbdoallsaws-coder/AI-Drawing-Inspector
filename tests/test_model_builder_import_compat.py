"""Pin opt-in reader/writer changes against the import writer at base commit 567f22a."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from tests.model_import_test_support import module as imports, textured_box
from tests.model_import_recipe_support import recipe as import_recipe, six_recipes
from tests.model_builder_test_support import ROOT, gltf, module, recipe, shape


def old_writer():
    source = ROOT / "tests/fixtures/model_builder/import_writer_567f22a.py"
    assert sha256(source.read_bytes()).hexdigest() == "cc7fc6d3fc8815609c020ef688077ad0018ae577d7867f6caeb156b6a47cc57d"
    # Relative imports still resolve into the isolated import test package.
    imports("writer")
    spec = importlib.util.spec_from_file_location("_model_import_tests.writer_at_567f22a", source)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    return legacy.write_glb


def textured_duplicate():
    fixture = textured_box()
    fixture.document["nodes"].append(deepcopy(fixture.document["nodes"][0]))
    fixture.document["nodes"][1]["translation"] = [2, 0, 0]
    fixture.document["scenes"][0]["nodes"].append(1)
    material = fixture.document["materials"][0]
    material.update(extras={"facilityDefaultFinish": "steel", "facilityDefaultFinishAdjustments": {"roughness": .4},
                            "facilityArtwork": True, "facilityFinishGroup": "labels"},
                    emissiveTexture={"index": 0}, emissiveFactor=[.5, .5, .5])
    return fixture


@pytest.mark.parametrize("case", range(7))
def test_default_inspect_prepare_files_and_glb_match_base_writer(tmp_path, monkeypatch, case):
    if case == 6:
        fixture, raw = textured_duplicate(), import_recipe()
    else:
        _, fixture, raw = six_recipes()[case]
    payload = fixture.bytes()
    legacy = old_writer()
    current = imports("writer").write_glb
    reader, prepare, worker = imports("reader"), imports("prepare"), imports("worker_task")
    source = reader.read_model(payload)
    assert current(source) == current(source, grouped=False, extended_materials=False) == legacy(source)
    outputs = []
    for name, writer in (("current", current), ("base", legacy)):
        job = tmp_path / name
        job.mkdir()
        (job / "source.bin").write_bytes(payload)
        (job / "recipe.json").write_bytes(imports("validation").json_bytes(raw))
        worker.execute_inspect(job)
        monkeypatch.setattr(prepare, "write_glb", writer)
        prepare.execute_prepare(job)
        outputs.append({p.name: p.read_bytes() for p in (job / "output").iterdir()})
    assert outputs[0] == outputs[1]  # GLB, identity, previews, manifest and catalog data.
    if case == 6:
        document = gltf(outputs[0]["model.glb"])
        assert len(document["nodes"]) == 2
        assert all("facilityDefaultFinish" not in m["extras"] and "emissiveTexture" not in m
                   for m in document["materials"])


def test_extended_material_round_trip_preserves_extras_and_emissive_texture():
    payload = textured_duplicate().bytes()
    old = imports("reader").read_model(payload)
    extended = imports("reader").read_model(payload, extended_materials=True)
    assert "defaultFinish" not in old.materials[0]
    assert "emissiveTexture" not in old.materials[0]
    material = extended.materials[0]
    assert material["defaultFinish"] == {"appearanceId": "steel", "roughness": .4}
    assert material["artwork"] is True and material["finishGroup"] == "labels"
    assert material["emissiveTexture"]["image"] == 0
    output = imports("writer").write_glb(extended, generator="model-builder-1", grouped=True, extended_materials=True)
    document = gltf(output)
    assert document["asset"]["generator"] == "model-builder-1"
    assert len(document["nodes"]) == 1
    assert len(document["meshes"][0]["primitives"]) == 1
    assert document["materials"][0]["emissiveTexture"] == {"index": 0, "texCoord": 0}
    reread = imports("reader").read_model(output, extended_materials=True)
    assert reread.materials[0]["defaultFinish"] == material["defaultFinish"]
    assert reread.materials[0]["finishGroup"] == "labels" and reread.materials[0]["artwork"]
    assert reread.parts[0].name == "node"  # Preserve node names, not the material display label.
    assert sum(len(p.indices) for p in reread.parts) == 24


def test_grouped_writer_combines_same_name_material_but_separates_other_materials():
    result = module("build").build_model(recipe(shape(), shape(id="b", material="other"),
        materials={"paint": {"color": "#112233"}, "other": {"color": "#334455"}}))
    model = deepcopy(result.model)
    model.parts.append(replace(model.parts[0], positions=model.parts[0].positions + [2, 0, 0]))
    output = imports("writer").write_glb(model, grouped=True, extended_materials=True)
    document = gltf(output)
    assert len(document["nodes"]) == 1
    assert len(document["meshes"][0]["primitives"]) == 2
    assert sum(document["accessors"][p["indices"]]["count"] for p in document["meshes"][0]["primitives"]) == 108


@pytest.mark.parametrize("extras", [
    {"facilityArtwork": "yes"}, {"facilityFinishGroup": ""}, {"facilityDefaultFinish": 1},
    {"facilityDefaultFinishAdjustments": {"roughness": .2}},
    {"facilityDefaultFinish": "steel", "facilityDefaultFinishAdjustments": {"roughness": 2}},
    {"facilityDefaultFinish": "steel", "facilityDefaultFinishAdjustments": {"color": "red"}},
    {"facilityDefaultFinish": "steel", "facilityDefaultFinishAdjustments": {"opacity": .2}},
])
def test_invalid_extensions_refuse_only_in_extended_mode(extras):
    fixture = textured_box()
    fixture.document["materials"][0]["extras"] = extras
    imports("reader").read_model(fixture.bytes())  # Existing importer ignores these extras.
    with pytest.raises(imports("errors").ModelImportError):
        imports("reader").read_model(fixture.bytes(), extended_materials=True)


@pytest.mark.parametrize("mode", ["different-transform", "uv1", "missing-uv"])
def test_extended_textures_refuse_uv_loss(mode):
    fixture = textured_box()
    material = fixture.document["materials"][0]
    material["emissiveTexture"] = {"index": 0}
    if mode == "different-transform":
        material["emissiveTexture"]["extensions"] = {"KHR_texture_transform": {"offset": [.1, 0]}}
    elif mode == "uv1":
        material["emissiveTexture"]["texCoord"] = 1
    else:
        del fixture.document["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"]
    imports("reader").read_model(fixture.bytes())
    with pytest.raises(imports("errors").ModelImportError) as caught:
        imports("reader").read_model(fixture.bytes(), extended_materials=True)
    assert caught.value.code == "gltf_texture_unsupported"


def test_emissive_only_texture_transform_is_baked_once():
    fixture = textured_box()
    material = fixture.document["materials"][0]
    del material["pbrMetallicRoughness"]["baseColorTexture"]
    material["emissiveTexture"] = {"index": 0, "extensions": {"KHR_texture_transform": {"offset": [.1, .2]}}}
    model = imports("reader").read_model(fixture.bytes(), extended_materials=True)
    assert model.parts[0].uv0[0] == pytest.approx([.1, .2])
    output = imports("writer").write_glb(model, extended_materials=True)
    reread = imports("reader").read_model(output, extended_materials=True)
    assert np.array_equal(reread.parts[0].uv0, model.parts[0].uv0)
    assert "emissiveTexture" in gltf(output)["materials"][0]
