"""Backend finish precedence for authored and included material metadata."""
from ai_inspector.codex_runtime.component_inventory import material_slots, shown_finish
from tests.model_builder_test_support import gltf, module, recipe, shape
from tests.model_builder_composition_support import CatalogFixture


def test_default_adjustments_are_flattened_and_part_override_wins():
    raw = recipe(shape(), materials={"paint": {"color": "#888888", "finish": {
        "appearanceId": "paint-machine-gray", "color": "#123456", "roughness": .2, "metalness": .4}}})
    built = module("build").build_model(raw, allowed_appearance_ids=["paint-machine-gray"])
    slot = material_slots(gltf(built.glb))[0]
    assert slot["defaultFinish"] == "paint-machine-gray"
    assert slot["defaultFinishAdjustments"] == {"color": "#123456", "roughness": .2, "metalness": .4}
    assert shown_finish(slot, {}, {})["color"] == "#123456"
    slot["savedOverride"] = {"color": "#abcdef", "roughness": .5, "metalness": 0}
    assert shown_finish(slot, {}, {})["color"] == "#abcdef"
    del slot["savedOverride"]
    assert shown_finish(slot, {}, {})["color"] == "#123456"


def test_invalid_adjustment_values_are_ignored_on_inspection():
    raw = recipe(shape(), materials={"paint": {"color": "#888888", "finish": {"appearanceId": "paint-machine-gray"}}})
    built = module("build").build_model(raw, allowed_appearance_ids=["paint-machine-gray"])
    document = gltf(built.glb)
    document["materials"][0]["extras"]["facilityDefaultFinishAdjustments"] = {
        "color": "red", "roughness": float("nan"), "metalness": True}
    slot = material_slots(document)[0]
    assert "defaultFinishAdjustments" not in slot


def test_printed_artwork_takes_its_part_override_but_no_default_or_object_finish():
    raw = recipe(shape("panel", center=[0, .05, 0], size=[.2, .1],
                       print={"background": "#ffffff", "items": [
                           {"text": "OUTBOUND", "box": [.1, .1, .9, .9], "color": "#000000"}]}),
                 size={"width": .2, "height": .1, "depth": .0025})
    built = module("build").build_model(raw)
    printed = next(slot for slot in material_slots(gltf(built.glb)) if slot.get("printedArtwork"))
    assert "defaultFinish" not in printed
    assert shown_finish(printed, {"appearance": {"color": "#ff0000"}}, {})["source"].startswith("printed artwork")
    # The user's own part finish still applies, as for any part (existing precedence, C6).
    printed["savedOverride"] = {"color": "#123456", "roughness": 1, "metalness": 1}
    assert shown_finish(printed, {"appearance": {"color": "#ff0000"}}, {})["color"] == "#123456"


def test_default_finish_inside_an_include_survives_to_inventory(tmp_path):
    fixture = CatalogFixture(tmp_path)
    source = recipe(shape(), materials={"paint": {"color": "#888888", "finish": {
        "appearanceId": "paint-machine-gray", "color": "#234567"}}})
    built_source = module("build").build_model(source, allowed_appearance_ids=["paint-machine-gray"])
    asset = fixture.add("finished", built_source.glb, dimensions=built_source.dimensions)
    entry, _ = fixture.include(asset)
    composed = fixture.build(recipe(entry), allowed_appearance_ids=["paint-machine-gray"])
    slot = next(slot for slot in material_slots(gltf(composed.glb)) if slot.get("defaultFinish"))
    assert slot["defaultFinishAdjustments"]["color"] == "#234567"
    assert shown_finish(slot, {}, {})["color"] == "#234567"
