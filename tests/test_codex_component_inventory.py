from copy import deepcopy
import pytest

from ai_inspector.codex_runtime.component_inventory import catalog_visual_path, material_slots
from ai_inspector.codex_runtime.policy import PilotError


def gltf():
    return {"scene": 0, "scenes": [{"nodes": [0, 2]}],
        "nodes": [{"name": "Frame", "mesh": 1, "children": [1]}, {"name": "Seat", "mesh": 0}, {"name": "Guide", "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "material": 0}]},
                   {"primitives": [{"attributes": {"POSITION": 0}, "material": 1}, {"attributes": {"POSITION": 0}, "material": 0}]}],
        "accessors": [{"min": [0, 0, 0], "max": [1, 2, 3]}],
        "materials": [{"name": "Black", "pbrMetallicRoughness": {"baseColorFactor": [0, 0, 0, 1]}},
                      {"name": "Steel", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": .8}}]}


def test_slots_follow_renderer_scene_order_not_mesh_array_order():
    slots = material_slots(gltf())
    assert [s["key"] for s in slots] == ["m0-s0", "m1-s0", "m2-s0", "m3-s0"]
    assert [s["label"] for s in slots] == ["Frame / Steel", "Frame / Black", "Seat / Black", "Guide / Black"]
    assert slots[0]["color"] == "#ffffff" and slots[0]["metalness"] == .8
    assert slots[1]["color"] == "#000000"
    assert slots[2]["localBounds"]["maximum"] == [1, 2, 3]


def test_line_primitives_do_not_shift_mesh_keys():
    doc = gltf()
    doc["meshes"][1]["primitives"][0]["mode"] = 1
    assert [s["key"] for s in material_slots(doc)] == ["m0-s0", "m1-s0", "m2-s0"]


@pytest.mark.parametrize("kind", ["cycle", "duplicate", "dynamic", "extension"])
def test_unsupported_scene_fails_closed(kind):
    doc = deepcopy(gltf())
    if kind == "cycle": doc["nodes"][1]["children"] = [0]
    if kind == "duplicate": doc["scenes"][0]["nodes"].append(1)
    if kind == "dynamic": doc["animations"] = [{}]
    if kind == "extension": doc["extensionsRequired"] = ["EXT_mesh_gpu_instancing"]
    with pytest.raises((ValueError, PilotError)):
        material_slots(doc)


@pytest.mark.parametrize("path", ["/../private.glb", "/generated/../../private.glb", "file:///C:/private.glb",
    "https://example.com/private.glb", "//server/file.glb", "/generated/%2e%2e/private.glb", "/static/secret.glb",
    "/generated/file.glb?secret=1", "/generated/file.png", "/generated/C:secret.glb"])
def test_catalog_path_cannot_escape_generated_store(tmp_path, path):
    with pytest.raises(PilotError):
        catalog_visual_path(path, tmp_path)


def test_encoded_catalog_name_is_resolved_in_owned_store(tmp_path):
    assert catalog_visual_path("/generated/gym/model%20one.glb", tmp_path) == tmp_path / "generated/gym/model one.glb"
