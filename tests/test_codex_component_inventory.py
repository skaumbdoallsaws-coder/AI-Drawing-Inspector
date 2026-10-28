from copy import deepcopy
from pathlib import Path
import re
from types import SimpleNamespace
import pytest

from ai_inspector.codex_runtime import facility_tools
from ai_inspector.codex_runtime.component_inventory import (VIEWER_NEUTRAL, catalog_visual_path, inspect_components,
                                                            material_slots, shown_finish)
from ai_inspector.codex_runtime.policy import PilotError
from ai_inspector.facility_layout.appearance_library import load_library


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
    assert [s["legacyKey"] for s in slots] == ["m0-s0", "m1-s0", "m2-s0", "m3-s0"]
    assert [s["key"] for s in slots] == ["p:Frame#0", "p:Frame#1", "p:Frame/Seat#0", "p:Guide#0"]
    assert [s["label"] for s in slots] == ["Frame / Steel", "Frame / Black", "Seat / Black", "Guide / Black"]
    assert slots[0]["modelColor"] == "#ffffff" and slots[0]["modelMetalness"] == .8
    assert slots[1]["modelColor"] == "#000000"
    # A bare "color" read as what the view shows; agents restated it as an override (pink rack crossmembers).
    assert not {"color", "roughness", "metalness"} & set(slots[0])
    assert slots[2]["localBounds"]["maximum"] == [1, 2, 3]


def test_line_primitives_do_not_shift_mesh_keys():
    doc = gltf()
    doc["meshes"][1]["primitives"][0]["mode"] = 1
    slots = material_slots(doc)
    assert [s["legacyKey"] for s in slots] == ["m0-s0", "m1-s0", "m2-s0"]
    # Stable keys keep the glTF primitive index, so a skipped line primitive changes nothing else.
    assert [s["key"] for s in slots] == ["p:Frame#1", "p:Frame/Seat#0", "p:Guide#0"]


def test_stable_keys_survive_reordering_and_mark_repeated_or_unnamed_nodes():
    doc = gltf()
    doc["nodes"] = [{"name": "Rack Bay", "children": [1, 2, 3]}, {"name": "Shelf", "mesh": 0},
                    {"name": "Shelf", "mesh": 0}, {"mesh": 0}]
    doc["scenes"] = [{"nodes": [0]}]
    assert [s["key"] for s in material_slots(doc)] == [
        "p:Rack%20Bay/Shelf~0#0", "p:Rack%20Bay/Shelf~1#0", "p:Rack%20Bay/@3#0"]
    reordered = gltf()
    reordered["nodes"] = [reordered["nodes"][2], reordered["nodes"][0], reordered["nodes"][1]]
    reordered["nodes"][1]["children"] = [2]
    reordered["scenes"] = [{"nodes": [1, 0]}]
    assert {s["key"] for s in material_slots(reordered)} == {s["key"] for s in material_slots(gltf())}


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


def test_viewer_neutral_matches_the_renderer():
    root = Path(__file__).resolve().parents[1]
    page = (root / "static/index.html").read_text(encoding="utf-8")
    adapter = (root / "static/facility_layout_three_adapter.js").read_text(encoding="utf-8")
    assert "#" + re.search(r"neutralAssetColor: 0x([0-9a-fA-F]{6})", page).group(1).lower() == VIEWER_NEUTRAL["color"]
    assert float(re.search(r"DEFAULT_ASSET_ROUGHNESS = ([\d.]+)", adapter).group(1)) == VIEWER_NEUTRAL["roughness"]
    assert float(re.search(r"DEFAULT_ASSET_METALNESS = ([\d.]+)", adapter).group(1)) == VIEWER_NEUTRAL["metalness"]


def test_slots_flag_the_finishes_the_view_keeps():
    doc = gltf()
    doc["materials"][0]["extras"] = {"facilityAuthoredFinish": True}
    doc["materials"][1]["extras"] = {"facilityArtwork": True}
    slots = material_slots(doc)
    assert [s.get("authoredFinish", False) for s in slots] == [False, True, True, True]
    assert not any("printedArtwork" in s for s in slots)  # artwork needs an image to print
    doc["materials"][1]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
    assert material_slots(doc)[0]["printedArtwork"] is True


def test_shown_color_follows_the_renderer_precedence():
    library = load_library()["appearances"]
    oak, yellow = library["wood-oak"], library["paint-safety-yellow"]
    layout = {"extensions": {"facilityAppearances": {"version": 1, "custom": [
        {"appearanceId": "custom-smoked-oak", "label": "Smoked oak", "baseAppearanceId": "wood-oak", "color": "#8a7b6a"}]}}}
    plain = {"key": "p:Leg#0", "modelColor": "#f45894", "modelRoughness": 1, "modelMetalness": 1}
    authored, artwork = {**plain, "authoredFinish": True}, {**plain, "printedArtwork": True}
    painted = {"appearance": {"appearanceId": "paint-safety-yellow"}}
    red = {"appearance": {"color": "#aa0000"}}

    def shown(slot, placement):
        return shown_finish(slot, placement, layout)

    assert {k: shown(plain, {})[k] for k in VIEWER_NEUTRAL} == VIEWER_NEUTRAL
    assert "#f45894" not in str(shown(plain, {}))  # the model file's color is not what the view shows
    assert shown(plain, red)["color"] == "#aa0000"
    assert shown(authored, {})["color"] == shown(authored, red)["color"] == "#f45894"
    assert [shown(authored, painted)[k] for k in ("color", "roughness", "metalness")] == [
        yellow["color"], yellow["roughness"], yellow["metalness"]]
    assert "color" not in shown(artwork, painted) and "artwork" in shown(artwork, painted)["source"]
    custom = shown(plain, {"appearance": {"appearanceId": "custom-smoked-oak", "roughness": 0.3}})
    assert (custom["color"], custom["roughness"], custom["metalness"]) == ("#8a7b6a", 0.3, oak["metalness"])
    assert custom["source"] == "object finish: Smoked oak"
    override = {"key": "p:Leg#0", "color": "#123456", "roughness": .2, "metalness": .9}
    assert shown({**artwork, "savedOverride": override}, painted)["color"] == "#123456"
    finish = shown({**plain, "savedOverride": {"key": "p:Leg#0", "appearanceId": "wood-oak"}}, painted)
    assert finish["color"] == oak["color"] and finish["source"].startswith("part override")
    assert "color" not in shown(plain, {"appearance": {"appearanceId": "custom-gone"}})


def test_inspection_reports_the_overrides_the_view_applies(monkeypatch):
    placement = {"placementId": "pl-rack", "componentMaterials": {"representation": "detail", "overrides": [
        {"key": "p:Frame#0", "color": "#123456", "roughness": .2, "metalness": .9},
        {"key": "m1-s0", "color": "#654321", "roughness": .2, "metalness": .9}]}}
    monkeypatch.setattr(facility_tools, "read_bound_layout", lambda *_: {"layout": {"placements": [placement]}})
    runtime = SimpleNamespace(service=SimpleNamespace(component_inventory_resolver=lambda *_: {"slots": material_slots(gltf())}))

    def colors(representation):
        result = inspect_components(runtime, None, {}, {"placementId": "pl-rack", "representation": representation})
        assert "never restate a color" in result["colorNote"]
        return {slot["key"]: slot["shown"]["color"] for slot in result["slots"]}

    # Stable keys follow the part into either visual; older traversal keys only fit the visual they were saved for.
    assert colors("overview") == {"p:Frame#0": "#123456", "p:Frame#1": VIEWER_NEUTRAL["color"],
                                  "p:Frame/Seat#0": VIEWER_NEUTRAL["color"], "p:Guide#0": VIEWER_NEUTRAL["color"]}
    assert colors("detail")["p:Frame#1"] == "#654321"
