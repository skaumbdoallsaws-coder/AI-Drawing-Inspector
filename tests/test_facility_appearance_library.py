"""Appearance, scene and equipment decal library: manifests, saved values and operations."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.appearance_library import LIBRARY_ROOT, library_summary, load_library
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.component_materials import normalize_component_materials
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.validate import validate_layout

IMAGE = "/api/facility-decal-images/site-a/" + "b" * 64 + ".png"


def layout():
    doc = json.loads((Path(__file__).parent / "fixtures/facility_layout/empty_cell.json").read_text())
    doc["placements"] = [dict(placementId=f"pl-{i}", assetId="asset-rack", assetDefinitionRevision="a" * 64,
        positionMode="manual", transform=dict(position=dict(x=i * 5, y=0, z=0), quaternion=dict(x=0, y=0, z=0, w=1), scale=1),
        snapRelationship=None, metadata={"instanceLabel": f"Rack {i}"}) for i in range(3)]
    return doc


def apply(doc, *operations):
    return apply_facility_layout_operations(doc, list(operations))["document"]


def set_appearance(ids, appearance):
    return {"op": "set_appearance", "placementIds": ids, "appearance": appearance}


# Library manifests -----------------------------------------------------------------

def test_manifests_are_complete_and_every_file_matches_its_recorded_hash():
    library = load_library()
    assert set(library["categories"]) == {"metals", "plastics", "wood", "rubber", "glass", "fabric", "paper", "paint", "stone"}
    assert 20 <= len(library["appearances"]) <= 30
    for row in library["appearances"].values():
        assert row["category"] in library["categories"]
        assert row["texture"] is None or row["texture"]["textureSetId"] in library["textureSets"]
    for texture_set in library["textureSets"].values():
        assert texture_set["source"]["license"] == "CC0-1.0"
        for path, info in texture_set["files"].items():
            data = (LIBRARY_ROOT / path).read_bytes()
            assert len(data) == info["bytes"] and hashlib.sha256(data).hexdigest() == info["sha256"], path
    for environment in library["environments"].values():
        data = (LIBRARY_ROOT / environment["file"]).read_bytes()
        assert data.startswith(b"#?RADIANCE") and hashlib.sha256(data).hexdigest() == environment["sha256"]
        assert environment["source"]["license"] == "CC0-1.0"
    for decal in library["decals"].values():
        data = (LIBRARY_ROOT / decal["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == decal["sha256"] and b"<script" not in data.lower()
        assert decal["source"]["license"] in ("Public domain", "CC0 1.0") and decal["aspect"] > 0


def test_requested_presets_and_tints_exist():
    rows = load_library()["appearances"]
    assert rows["cardboard-kraft"]["color"] == "#b58f60"
    assert rows["paper-ivory-matte"]["color"] == "#ebe4d4"
    for required in ("wood-maple", "wood-oak", "wood-walnut", "steel-brushed", "steel-polished", "aluminum-brushed",
                     "aluminum-polished", "brass-brushed", "brass-polished", "plastic-matte", "plastic-glossy",
                     "rubber-black", "fabric-woven-gray", "glass-clear", "concrete-smooth", "paint-machine-gray"):
        assert required in rows
    for wood in ("wood-maple", "wood-oak", "wood-walnut"):
        assert "visual" in rows[wood]["label"].lower() and "not a certified" in rows[wood]["description"]
    assert rows["glass-clear"]["model"] == "physical" and rows["glass-clear"]["transmission"] == 1
    assert rows["cardboard-kraft"]["texture"]["sizeMeters"] < rows["wood-oak"]["texture"]["sizeMeters"]
    assert rows["wood-oak"]["texture"]["grain"] == "part" and rows["steel-brushed"]["texture"]["grain"] == "part"


def test_sage_can_list_the_library_and_propose_finishes_and_scenes():
    from jsonschema import Draft202012Validator
    from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
    from ai_inspector.codex_runtime.library_tools import list_library, tool_specs
    Draft202012Validator(tool_specs()[0]["input_schema"]).validate({"kind": "appearances", "category": "wood"})
    listed = list_library({"kind": "appearances", "category": "wood"})
    assert {row["appearanceId"] for row in listed["items"]} == {"wood-maple", "wood-oak", "wood-walnut"}
    validator = Draft202012Validator(operation_batch_schema())
    good = [{"op": "set_appearance", "placementIds": ["pl-0"], "appearance": {"appearanceId": "wood-oak", "grain": "length"}},
            {"op": "set_appearance", "placementIds": ["pl-1"], "color": None},
            {"op": "set_scene", "scene": {"version": 1, "sceneId": "warehouse", "adjustments": {"shadows": True}}}]
    for operation in good:
        assert not list(validator.iter_errors({"operations": [operation]})), operation
    bad = [{"op": "set_appearance", "placementIds": ["pl-0"], "color": "#000000", "appearance": None},
           {"op": "set_appearance", "placementIds": ["pl-0"], "appearance": {"appearanceId": "wood-oak", "density": 1}},
           {"op": "set_scene", "scene": {"version": 1, "sceneId": "moon-base"}}]
    for operation in bad:
        assert list(validator.iter_errors({"operations": [operation]})), operation


def test_agent_summary_filters_without_paths_or_provenance():
    metals = library_summary("appearances", category="metals")
    assert metals and all(row["category"] == "metals" for row in metals)
    assert all("thumbnail" not in row and "source" not in row for row in metals)
    assert [row["appearanceId"] for row in library_summary("appearances", query="kraft")] == ["cardboard-kraft"]
    assert any(row["sceneId"] == "machine-shop" for row in library_summary("scenes"))


# Placement appearances ----------------------------------------------------------------

def test_library_appearance_is_instance_local_and_leaves_engineering_data_alone():
    original = layout()
    before = deepcopy(original)
    doc = apply(original, set_appearance(["pl-0"], {"appearanceId": "wood-oak", "sizeMeters": 0.8, "grain": "length",
                                                   "rotationDegrees": 90, "roughness": 0.4}))
    assert original == before
    assert doc["placements"][0]["appearance"] == {"appearanceId": "wood-oak", "grain": "length", "rotationDegrees": 90,
                                                  "roughness": 0.4, "sizeMeters": 0.8}
    assert doc["placements"][1] == before["placements"][1] and doc["placements"][2] == before["placements"][2]
    changed = {key: value for key, value in doc["placements"][0].items() if key != "appearance"}
    assert changed == before["placements"][0]
    validate_layout(doc)
    assert layout_revision(doc) != layout_revision(original)
    assert apply(doc, set_appearance(["pl-0"], None)) == original


def test_legacy_color_still_works_and_can_be_replaced_by_a_finish():
    doc = apply(layout(), {"op": "set_appearance", "placementIds": ["pl-1"], "color": "#2478BC"})
    assert doc["placements"][1]["appearance"] == {"color": "#2478bc"}
    doc = apply(doc, set_appearance(["pl-1"], {"appearanceId": "steel-brushed"}))
    assert doc["placements"][1]["appearance"] == {"appearanceId": "steel-brushed"}
    validate_layout(doc)


@pytest.mark.parametrize("operation", [
    set_appearance(["pl-0"], {"appearanceId": "unobtainium"}),
    set_appearance(["pl-0"], {"appearanceId": "wood-oak", "roughness": 2}),
    set_appearance(["pl-0"], {"appearanceId": "wood-oak", "grain": "diagonal"}),
    set_appearance(["pl-0"], {"appearanceId": "wood-oak", "density": 700}),
    set_appearance(["pl-0"], {"appearanceId": "wood-oak", "offsetMeters": [1]}),
    set_appearance(["pl-0"], {"color": "#123456", "opacity": 0.5}),
    {"op": "set_appearance", "placementIds": ["pl-0"], "color": "#123456", "appearance": None},
    {"op": "set_appearance", "placementIds": ["pl-0"]},
    set_appearance(["pl-0", "pl-missing"], {"appearanceId": "wood-oak"}),
])
def test_invalid_appearance_operations_reject_the_whole_batch(operation):
    doc = layout()
    before = deepcopy(doc)
    with pytest.raises(FacilityLayoutError):
        apply(doc, operation)
    assert doc == before


def test_save_validation_rejects_unknown_or_malformed_finishes():
    doc = layout()
    doc["placements"][0]["appearance"] = {"appearanceId": "custom-missing"}
    with pytest.raises(FacilityLayoutError):
        validate_layout(doc)
    doc["placements"][0]["appearance"] = {"appearanceId": "wood-oak", "metalness": -1}
    with pytest.raises(FacilityLayoutError):
        validate_layout(doc)


# Custom finishes saved with the layout ----------------------------------------------------

def custom(*rows):
    return {"op": "set_custom_appearances", "appearances": {"version": 1, "custom": list(rows)}}


def test_custom_finishes_round_trip_and_cannot_be_deleted_while_in_use():
    smoked = {"appearanceId": "custom-smoked-oak", "label": " Smoked oak ", "baseAppearanceId": "wood-oak",
              "color": "#8A7B6A", "sizeMeters": 0.6}
    doc = apply(layout(), custom(smoked), set_appearance(["pl-2"], {"appearanceId": "custom-smoked-oak"}))
    stored = doc["extensions"]["facilityAppearances"]["custom"][0]
    assert stored["label"] == "Smoked oak" and stored["color"] == "#8a7b6a"
    validate_layout(doc)
    with pytest.raises(FacilityLayoutError) as caught:
        apply(doc, custom())
    assert caught.value.code == "custom_appearance_in_use"
    cleared = apply(doc, set_appearance(["pl-2"], None), custom())
    assert "facilityAppearances" not in cleared.get("extensions", {})
    validate_layout(cleared)


@pytest.mark.parametrize("row", [
    {"appearanceId": "smoked", "label": "x", "baseAppearanceId": "wood-oak"},
    {"appearanceId": "custom-a", "label": "", "baseAppearanceId": "wood-oak"},
    {"appearanceId": "custom-a", "label": "x", "baseAppearanceId": "custom-b"},
    {"appearanceId": "custom-a", "label": "x", "baseAppearanceId": "wood-oak", "strength": 1},
])
def test_invalid_custom_finishes_are_rejected(row):
    with pytest.raises(FacilityLayoutError):
        apply(layout(), custom(row))


# Scenes -----------------------------------------------------------------------------

def test_scene_is_saved_with_the_layout_and_removed_by_null():
    doc = apply(layout(), {"op": "set_scene", "scene": {"version": 1, "sceneId": "machine-shop",
                                                        "adjustments": {"exposure": 1.1, "shadows": True, "background": "#EEF0F2"}}})
    assert doc["extensions"]["facilityScene"] == {"version": 1, "sceneId": "machine-shop",
                                                  "adjustments": {"background": "#eef0f2", "exposure": 1.1, "shadows": True}}
    assert doc["placements"] == layout()["placements"]
    validate_layout(doc)
    assert "facilityScene" not in apply(doc, {"op": "set_scene", "scene": None})["extensions"]


@pytest.mark.parametrize("scene", [
    {"version": 1, "sceneId": "moon-base"},
    {"version": 2, "sceneId": "classic"},
    {"version": 1, "sceneId": "classic", "adjustments": {"exposure": 9}},
    {"version": 1, "sceneId": "classic", "adjustments": {"fog": 1}},
    {"version": 1, "sceneId": "classic", "adjustments": {"shadows": "yes"}},
])
def test_invalid_scenes_are_rejected(scene):
    with pytest.raises(FacilityLayoutError):
        apply(layout(), {"op": "set_scene", "scene": scene})


# Equipment decals ----------------------------------------------------------------------

def decal(**patch):
    return dict(dict(decalId="edecal-1", label="Forklift warning", imagePath=IMAGE, placementId="pl-1",
                     anchor={"position": {"x": 0.1, "y": 1.2, "z": 0.45}, "normal": {"x": 0, "y": 0, "z": 2},
                             "rotationDegrees": 0}, widthMeters=0.3, heightMeters=0.26, libraryDecalId="iso7010-w014"), **patch)


def decals(*rows):
    return {"op": "set_equipment_decals", "decals": {"version": 1, "decals": list(rows)}}


def test_equipment_decals_bind_to_one_placement_and_go_away_with_it():
    doc = apply(layout(), decals(decal()))
    stored = doc["extensions"]["facilityEquipmentDecals"]["decals"][0]
    assert stored["anchor"]["normal"] == {"x": 0, "y": 0, "z": 1}
    assert doc["placements"] == layout()["placements"]
    validate_layout(doc)
    removed = apply(doc, {"op": "delete_placement", "placementId": "pl-1"})
    assert removed["extensions"]["facilityEquipmentDecals"]["decals"] == []
    replaced = apply(doc, {"op": "replace_asset", "placementId": "pl-1", "assetId": "asset-bench",
                           "assetDefinitionRevision": "c" * 64})
    assert replaced["extensions"]["facilityEquipmentDecals"]["decals"] == []


@pytest.mark.parametrize("patch", [
    {"imagePath": "https://example.com/sign.png"},
    {"imagePath": "/api/facility-decal-images/site-b/" + "b" * 64 + ".png"},
    {"placementId": "pl-missing"},
    {"decalId": "decal-1"},
    {"widthMeters": 0},
    {"anchor": {"position": {"x": 0, "y": 0, "z": 0}, "normal": {"x": 0, "y": 0, "z": 0}, "rotationDegrees": 0}},
    {"libraryDecalId": "iso7010-x999"},
])
def test_invalid_equipment_decals_are_rejected(patch):
    with pytest.raises(FacilityLayoutError):
        apply(layout(), decals(decal(**patch)))


# Part finishes ------------------------------------------------------------------------

def test_part_finishes_accept_stable_keys_and_library_appearances():
    value = normalize_component_materials({"representation": "detail", "overrides": [
        {"key": "p:Chair_Assy/Seat~1/basebody_imported1#0", "appearanceId": "fabric-woven-navy", "sizeMeters": 0.1},
        {"key": "m3-s0", "color": "#AABBCC", "roughness": 0.5, "metalness": 0},
    ]})
    assert value["overrides"][0] == {"key": "m3-s0", "color": "#aabbcc", "roughness": 0.5, "metalness": 0}
    assert value["overrides"][1]["appearanceId"] == "fabric-woven-navy"
    doc = apply(layout(), {"op": "set_component_materials", "placementId": "pl-0", "materials": value})
    validate_layout(doc)
    for bad in ({"key": "p:#0", "appearanceId": "wood-oak"}, {"key": "p:a b#0", "appearanceId": "wood-oak"},
                {"key": "p:a//b#0", "appearanceId": "wood-oak"}, {"key": "seat", "color": "#000000", "roughness": 0, "metalness": 0},
                {"key": "p:a#0", "appearanceId": "wood-oak", "metalness": 3}):
        with pytest.raises(ValueError):
            normalize_component_materials({"representation": "detail", "overrides": [bad]})
