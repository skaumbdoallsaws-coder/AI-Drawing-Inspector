"""Kernel integration, reference parity, stable parts, normalization and lints."""
from copy import deepcopy
from hashlib import sha256
import json
import os
import subprocess
import sys
import time

import numpy as np
import pytest

from tests.model_builder_test_support import PACKAGE, REFERENCE, ROOT, gltf, include, module, recipe, reference, shape

builder = module("build")
Error = module("errors").ModelBuildError


def codes(result):
    return {finding["code"] for finding in result.lints}


@pytest.mark.parametrize("name,baseline", [
    ("baler-vertical-42", "baler"), ("gaylord-on-pallet", "gaylord"),
    ("pack-station-printer", "pack-station"), ("carrier-tag-ups", "carrier-tag"),
    ("pallet-plain", None), ("roll-cage-plain", None)])
def test_six_mb0_recipes_build_and_verify_bounds_and_functional_names(name, baseline):
    from ai_inspector.industrial_assets.primitives import verify
    raw = reference(name)
    result = builder.build_model(raw)
    checked = verify(result.glb, result.dimensions, base_height=raw.get("hangHeight", 0))
    assert checked["triangles"] == result.triangles == result.budgets["triangles"]
    document = gltf(result.glb)
    names = {n["name"] for n in document["nodes"]}
    assert len(names) == len(document["nodes"])
    assert all(m["extras"]["facilityAuthoredFinish"] for m in document["materials"])
    for part in result.model.parts:
        triangle = part.positions[part.indices]
        geometric = np.cross(triangle[:,1]-triangle[:,0], triangle[:,2]-triangle[:,0])
        assert np.all(np.einsum("ij,ikj->ik", geometric, part.normals[part.indices]) > 0)
        assert np.linalg.norm(part.normals, axis=1) == pytest.approx(np.ones(len(part.normals)), abs=1e-6)
    low, high = module("scene").bounds(result.components)
    if baseline:
        stats = json.loads((REFERENCE / "baseline-stats.json").read_text())[baseline]
        assert low == pytest.approx(stats["bounds"]["min"], abs=.01)
        assert high == pytest.approx(stats["bounds"]["max"], abs=.01)
        expected = set(stats["parts"])
        if baseline == "gaylord":
            expected = {name for name in expected if not name.startswith("User Library-pallet")}
            expected |= {"pallet boards", "pallet blocks"}
            pallet = [c for c in result.components if c.entry["name"].startswith("pallet ")]
            a, b = module("scene").bounds(pallet)
            assert b-a == pytest.approx([1.2, .132, 1], abs=2e-6)
            assert len(pallet) == 23  # 3 runners, 9 blocks, 3 stringers, 8 deck boards (C42)
        assert names == expected
    else:
        assert result.dimensions == pytest.approx(raw["size"], abs=2e-6)
        assert names == ({"pallet boards", "pallet blocks"} if name == "pallet-plain" else
                         {"cage wheels", "cage frame", "cage deck", "cage top rail", "cage mesh"})
    assert "size_mismatch" not in codes(result)
    assert result.lints == []  # the MB0 references are clean (flicker, floating and size checks)
    assert "front_check" not in codes(result)


def test_one_name_one_node_primitives_per_material_and_entry_instance_map():
    result = builder.build_model(recipe(
        shape(id="left", mirror={"plane": "x"}),
        shape(id="right", material="metal"),
        {"id": "frame", "group": [shape(id="brace")]},
        materials={"paint": {"color": "#52708a"}, "metal": {"color": "#bbbbbb", "metalness": 1}}))
    document = gltf(result.glb)
    assert len(document["nodes"]) == len(document["meshes"]) == 1
    assert len(document["meshes"][0]["primitives"]) == 2
    assert len(result.model.parts) == 2
    assert result.triangles == 48
    assert result.part_map["entries"]["left"] == result.part_map["entries"]["brace"]
    assert result.part_map["entries"]["frame"] == result.part_map["entries"]["brace"]
    assert result.part_map["entries"]["left"] != result.part_map["entries"]["right"]
    assert set(result.part_map["instances"]) == {"left[0]", "left[1]", "right[0]", "frame[0]", "frame[0]/brace[0]"}
    assert set(p.key for p in result.model.parts) == {"p:housing#0", "p:housing#1"}
    assert {m["name"] for m in document["materials"]} == {"housing (paint)", "housing (metal)"}


def test_all_materials_authored_finish_adjustments_and_flat_print_uv():
    result = builder.build_model(recipe(shape(), shape("panel", id="screen", name="display", material="screen"),
        materials={"paint": {"color": "#52708a", "finish": {"appearanceId": "steel",
                    "color": "#aabbcc", "roughness": .3, "metalness": .8}},
                   "screen": {"color": "#112233", "lit": .5}}), allowed_appearance_ids=["steel"])
    document = gltf(result.glb)
    paint = next(m for m in document["materials"] if "facilityDefaultFinish" in m["extras"])
    assert paint["extras"]["facilityDefaultFinish"] == "steel"
    assert paint["extras"]["facilityDefaultFinishAdjustments"] == dict(color="#aabbcc", roughness=.3, metalness=.8)
    artwork = next(m for m in document["materials"] if m["extras"].get("facilityArtwork"))
    assert "facilityDefaultFinish" not in artwork["extras"]
    assert max(artwork["emissiveFactor"]) > 0
    assert "images" not in document  # Prints rasterize only in MB2.
    assert next(p for p in result.model.parts if p.name == "display" and p.uv0 is not None).uv0.shape == (6, 2)
    assert result.warnings


def test_component_keys_match_renderer_encoding_and_long_name_fallback():
    result = builder.build_model(recipe(shape(name="  rail / \u03b2~  ")))
    assert result.part_map["entries"]["body"] == ["p:rail%20%2F%20%CE%B2%7E#0"]
    result = builder.build_model(recipe(shape(name="\u4e00"*80)))
    assert result.part_map["entries"]["body"] == ["p:@0#0"]


def test_explicit_zero_hang_height_keeps_floor_model_bytes():
    assert builder.build_model(recipe()).glb == builder.build_model(recipe(hangHeight=0)).glb


def test_shift_surfaces_footprint_and_hang_height_use_distinct_dimensions():
    from ai_inspector.industrial_assets.primitives import verify
    result = builder.build_model(recipe(shape(min=[2,-2,3], max=[4,-1,7]), hangHeight=.6,
        size={"width": 2, "height": 1, "depth": 4}, surfaces=[
            {"id": "deck", "label": "Deck", "height": -1, "rect": [2,3,4,7]}]))
    assert result.shift == pytest.approx([-3, 2.6, -5])
    assert result.dimensions == pytest.approx({"width": 2, "height": 1, "depth": 4})
    assert result.catalog_dimensions == pytest.approx({"width": 2, "height": 1.6, "depth": 4})
    assert result.surfaces[0]["localFrame"]["origin"] == pytest.approx({"x": 0, "y": 1.6, "z": 0})
    assert result.surfaces[0]["bounds"] == pytest.approx(
        {"minimumX": -1, "maximumX": 1, "minimumZ": -2, "maximumZ": 2})
    assert len(result.footprint[0]) == 4
    verify(result.glb, result.dimensions, base_height=.6)
    with pytest.raises(ValueError):
        verify(result.glb)
    with pytest.raises(ValueError):
        verify(result.glb, result.catalog_dimensions, base_height=.6)
    assert result.provenance["hangHeight"] == .6
    with pytest.raises(Error) as caught:
        builder.build_model(recipe(surfaces=[{"id": "deck", "label": "Deck", "height": 2, "rect": [0,0,.1,.1]}]))
    assert caught.value.code == "schema_invalid"
    assert caught.value.path == "$.surfaces[0]"


@pytest.mark.parametrize("base_height", [-.01, 3.01, True, float("nan"), float("inf")])
def test_verify_refuses_invalid_base_height(base_height):
    from ai_inspector.industrial_assets.primitives import verify
    with pytest.raises(ValueError, match="base_height"):
        verify(b"", base_height=base_height)


def test_includes_refuse_composition_until_mb3():
    with pytest.raises(Error) as caught:
        builder.build_model(recipe({"id": "assembly", "group": [include()]}))
    assert caught.value.code == "composition_unavailable"
    assert caught.value.path == "$.entries[0].group[0].include"
    assert "MB3" in str(caught.value)


def test_budget_refuses_before_geometry_expands(monkeypatch):
    def forbidden(*args):
        pytest.fail("geometry expanded before budget refusal")
    monkeypatch.setattr(builder, "expand", forbidden)
    with pytest.raises(Error) as caught:
        builder.build_model(recipe(shape("sphere", repeat={"count": 114, "step": [0,0,0]})))
    assert caught.value.code == "budget_exceeded"


def test_transformed_coordinates_refuse_bounded_builder_error():
    with pytest.raises(Error) as caught:
        builder.build_model(recipe({"id": "group", "position": [15,0,0], "group": [shape()]}))
    assert caught.value.code == "geometry_invalid"
    assert caught.value.path == "$.entries[0].group[0]"


def test_same_recipe_same_bytes_twice_and_private_second_process(tmp_path):
    raw = reference("gaylord-on-pallet")
    first, second = builder.build_model(raw), builder.build_model(raw)
    assert first.glb == second.glb
    assert first.lints == second.lints and first.part_map == second.part_map
    assert first.shift == second.shift
    source = tmp_path / "recipe.json"
    source.write_text(json.dumps(raw), encoding="utf-8", newline="\n")
    script = r'''
import importlib.util, importlib.abc, hashlib, json, sys
from pathlib import Path
class NoApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == "ai_inspector" or fullname.startswith("ai_inspector."):
            raise AssertionError("application import: " + fullname)
sys.meta_path.insert(0, NoApplication())
sys.path.append(sys.argv[3])
package = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("_model_builder_worker", package / "__init__.py",
    submodule_search_locations=[str(package)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from _model_builder_worker.build import build_model
result = build_model(json.loads(Path(sys.argv[2]).read_text()))
assert "_model_import_worker" in sys.modules
assert not any(n == "ai_inspector" or n.startswith("ai_inspector.") for n in sys.modules)
print(hashlib.sha256(result.glb).hexdigest())
'''
    dependencies = str(__import__("pathlib").Path(np.__file__).resolve().parent.parent)
    command = [sys.executable, "-I", "-S", "-B", "-c", script, str(PACKAGE), str(source), dependencies]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=40, check=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert completed.stdout.strip() == sha256(first.glb).hexdigest()


def test_every_lint_positive_and_normal_negative():
    normal = builder.build_model(recipe(shape(), shape("panel", id="label", name="label"),
                                       front=["label"], fitsWithin={"width": 1.1, "depth": 1.1, "height": 1.1}))
    assert not normal.lints
    cases = [
        ("size_mismatch", recipe(size={"width": 2, "height": 1, "depth": 1})),
        ("floor_shift", recipe(shape(min=[0,1,0], max=[1,2,1]))),
        ("floating_part", recipe(shape(), shape(id="lamp", name="lamp", min=[0,2,0], max=[.1,2.1,.1]))),
        ("front_check", recipe(shape(), shape("panel", id="label", name="label", facing="-z"), front=["label"])),
        ("coplanar_overlap", recipe(shape(), shape(id="layer", material="other"),
                                   materials={"paint": {"color": "#333333"}, "other": {"color": "#ffffff"}})),
        ("generic_name", recipe(shape(name="Box 12"))),
        ("heavy", recipe(shape("sphere", repeat={"count": 40, "step": [0,0,0]}))),
        ("tiny_part", recipe(shape(min=[0,0,0], max=[.001,.001,.001]))),
        ("fit_exceeded", recipe(fitsWithin={"width": .9, "depth": 1})),
    ]
    for code, raw in cases:
        assert code in codes(builder.build_model(raw)), code


def test_opposite_contact_faces_are_not_coplanar_overlap_and_hung_floor_is_intentional():
    result = builder.build_model(recipe(shape(min=[-.5,0,-.5], max=[0,1,.5]),
        shape(id="other", material="other", min=[0,0,-.5], max=[.5,1,.5]),
        materials={"paint": {"color": "#111111"}, "other": {"color": "#222222"}}))
    assert "coplanar_overlap" not in codes(result)
    assert "floating_part" not in codes(result)
    hung = builder.build_model(reference("carrier-tag-ups"))
    assert "floor_shift" not in codes(hung)
    raw = reference("carrier-tag-ups")
    raw["fitsWithin"] = {"width": 1, "depth": 1, "height": .5}
    assert "fit_exceeded" in codes(builder.build_model(raw))


def test_lints_are_capped_and_dense_contact_work_is_bounded():
    start = time.perf_counter()
    value = recipe({"id": "assembly", "repeat": {"count": 15, "step": [0,0,0]},
                    "group": [shape(repeat={"count": 200, "step": [0,0,0]})]})
    result = builder.build_model(value)
    assert len(result.components) == 3000
    assert any("100000-pair" in warning for warning in result.warnings)
    assert "floating_part" not in codes(result)  # No false claims after contact truncation.
    assert time.perf_counter()-start < 30
    counts = {}
    for finding in result.lints:
        counts[finding["code"]] = counts.get(finding["code"], 0)+1
    assert all(count <= 20 for count in counts.values())
    # Truly isolated pieces, one touching floor, produce a capped set of floating diagnostics.
    pieces = [shape(id=f"p-{i}", min=[-.5, i*.2, -.5], max=[.5, i*.2+.01, .5]) for i in range(30)]
    result = builder.build_model(recipe(*pieces))
    assert sum(f["code"] == "floating_part" for f in result.lints) == 20
