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
from ai_inspector.facility_layout.plan_settings import default_plan_settings
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
    assert set(library["categories"]) == {"metals", "plastics", "wood", "rubber", "glass", "fabric", "paper", "paint", "stone",
                                          "lights"}
    assert 20 <= sum(row["category"] != "lights" for row in library["appearances"].values()) <= 30
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


def test_lights_glow_in_the_facility_view_and_stay_out_of_the_assembly_lists():
    from ai_inspector.assembly_knowledge.assembly_appearance import AssemblyAppearanceError, finish
    from ai_inspector.codex_runtime.library_tools import list_library, tool_specs
    library = load_library()
    lights = {key for key, row in library["appearances"].items() if row["category"] == "lights"}
    assert lights == {"light-cool-white-led", "light-warm-white", "light-exit-green", "light-beacon-amber", "light-alarm-red",
                      "light-signal-blue", "light-stack-red", "light-stack-amber", "light-stack-green",
                      "light-pole-led", "light-wall-led", "light-dock-led", "light-accent-spot"}
    for row in library["appearances"].values():
        # Only the Lights glow; each keeps an unlit color (the plastic when switched off) and a rendered thumbnail.
        assert bool(row.get("emission")) == (row["category"] == "lights"), row["appearanceId"]
        if row.get("emission"):
            assert row["texture"] is None and row["emission"]["color"] != row["color"] and row["emission"]["intensity"] == 1
            assert (LIBRARY_ROOT / row["thumbnail"]).is_file()
    # Sage lists them with their glow color and is told what a color override does on one.
    assert "set_component_materials" in tool_specs()[0]["description"] and "glow" in tool_specs()[0]["description"]
    listed = list_library({"kind": "appearances", "category": "lights"})
    assert {row["appearanceId"] for row in listed["items"]} == lights
    assert all(row["emission"]["color"].startswith("#") for row in listed["items"])
    # The beacon turns, the alarm strobes and the signal blinks, once a second; Sage sees the pattern and is told.
    patterns = {row["appearanceId"]: (row["emission"].get("pattern", "steady"), row["emission"].get("periodSeconds"))
                for row in listed["items"]}
    assert {key: value for key, value in patterns.items() if value[0] != "steady"} == {
        "light-beacon-amber": ("rotate", 1), "light-alarm-red": ("strobe", 1), "light-signal-blue": ("blink", 1)}
    assert all(value[1] is None for value in patterns.values() if value[0] == "steady")
    # The outdoor ones have a beam angle (L8): the evening scene shows a beam and a pool where it lands.
    beams = {row["appearanceId"]: row["emission"].get("beamAngleDegrees") for row in listed["items"]}
    assert {key: value for key, value in beams.items() if value} == {
        "light-pole-led": 110, "light-wall-led": 100, "light-dock-led": 70, "light-accent-spot": 30}
    # The accent spot (2026-11-02) lights what its lens faces in the evening scene, with a spot light, not a pool.
    accents = {row["appearanceId"] for row in listed["items"] if row["emission"].get("accent")}
    assert accents == {"light-accent-spot"}
    accent = library["appearances"]["light-accent-spot"]
    assert accent["label"] == "Accent spot LED" and accent["estimate"]["lumens"] == 700
    assert accent["estimate"]["beamAngleDegrees"] == 30 and "8 m" in accent["description"]
    assert "Accent spot LED (emission.accent)" in tool_specs()[0]["description"]
    assert "emission.beamAngleDegrees" in tool_specs()[0]["description"]
    from ai_inspector.facility_layout.appearance_library import _valid_emission
    assert _valid_emission({"color": "#ffffff", "intensity": 1, "beamAngleDegrees": 10})
    assert not _valid_emission({"color": "#ffffff", "intensity": 1, "beamAngleDegrees": 170})
    assert not _valid_emission({"color": "#ffffff", "intensity": 1, "beamAngleDegrees": "wide"})
    assert _valid_emission({"color": "#ffffff", "intensity": 1, "beamAngleDegrees": 30, "accent": True})
    assert not _valid_emission({"color": "#ffffff", "intensity": 1, "accent": True}), "an accent spot has a beam"
    assert not _valid_emission({"color": "#ffffff", "intensity": 1, "beamAngleDegrees": 30, "accent": False})
    assert not _valid_emission({"color": "#ffffff", "intensity": 1, "beamAngleDegrees": 30, "accent": 1})
    assert "emission.pattern" in tool_specs()[0]["description"]
    assert "Lights finish: the light's color, lit and unlit" in listed["adjustments"]
    assert all("emission" not in row for row in library_summary("appearances", category="metals"))
    assert {row["appearanceId"] for row in library_summary("appearances", glow=True)} == lights
    assert library_summary("appearances", query="stack", glow=False) == []
    # A lamp's lens takes one like any part finish, with the glow color overridden.
    doc = apply(layout(), {"op": "set_component_materials", "placementId": "pl-0", "materials": {"representation": "detail",
        "overrides": [{"key": "p:row/lens#0", "appearanceId": "light-cool-white-led", "color": "#fff4e0"}]}})
    validate_layout(doc)
    # The Assembly view draws no glow, so its finishes refuse one.
    with pytest.raises(AssemblyAppearanceError, match="Lights finish"):
        finish({"appearanceId": "light-stack-green"})
    assert finish({"appearanceId": "paint-machine-gray"})["appearanceId"] == "paint-machine-gray"


@pytest.mark.parametrize("emission", [{"color": "green", "intensity": 1}, {"color": "#00ff00"},
                                      {"color": "#00ff00", "intensity": 0}, {"color": "#00ff00", "intensity": True},
                                      {"color": "#00ff00", "intensity": 1, "pattern": "blink"}, "#00ff00",
                                      {"color": "#00ff00", "intensity": 1, "pattern": "pulse", "periodSeconds": 1},
                                      {"color": "#00ff00", "intensity": 1, "pattern": "blink", "periodSeconds": 0.2},
                                      {"color": "#00ff00", "intensity": 1, "pattern": "blink", "periodSeconds": True},
                                      {"color": "#00ff00", "intensity": 1, "periodSeconds": 1},
                                      {"color": "#00ff00", "intensity": 1, "pattern": "steady", "periodSeconds": 1},
                                      {"color": "#00ff00", "intensity": 1, "pattern": "cycle", "periodSeconds": 1},
                                      {"color": "#00ff00", "intensity": 1, "pattern": "blink", "periodSeconds": 20},
                                      {"color": "#00ff00", "intensity": 1, "pattern": "blink", "periodSeconds": 1,
                                       "cycleColors": ["#ff0000", "#0000ff"]},
                                      {"color": "#00ff00", "intensity": 1, "pattern": "cycle", "periodSeconds": 20,
                                       "cycleColors": ["#ff0000"]},
                                      {"color": "#00ff00", "intensity": 1, "pattern": "cycle", "periodSeconds": 20,
                                       "cycleColors": ["#ff0000", "blue"]}])
def test_a_malformed_emission_stops_the_library_from_loading(tmp_path, emission):
    for name in ("appearances", "scenes", "decals"):
        (tmp_path / f"{name}.json").write_bytes((LIBRARY_ROOT / f"{name}.json").read_bytes())
    doc = json.loads((tmp_path / "appearances.json").read_text(encoding="utf-8"))
    next(row for row in doc["appearances"] if row["appearanceId"] == "light-exit-green")["emission"] = emission
    (tmp_path / "appearances.json").write_bytes(json.dumps(doc).encode("utf-8"))
    with pytest.raises(ValueError, match="invalid emission"):
        load_library(str(tmp_path))


@pytest.mark.parametrize("emission", [{"color": "#00ff00", "intensity": 1, "pattern": "steady"},
                                      {"color": "#00ff00", "intensity": 2, "pattern": "strobe", "periodSeconds": 0.5},
                                      {"color": "#00ff00", "intensity": 1, "pattern": "cycle", "periodSeconds": 60},
                                      {"color": "#00ff00", "intensity": 1, "pattern": "cycle", "periodSeconds": 2,
                                       "cycleColors": ["#ff0000", "#00ff00", "#0000ff"]}])
def test_a_light_may_carry_a_pattern_with_its_period(tmp_path, emission):
    for name in ("appearances", "scenes", "decals"):
        (tmp_path / f"{name}.json").write_bytes((LIBRARY_ROOT / f"{name}.json").read_bytes())
    doc = json.loads((tmp_path / "appearances.json").read_text(encoding="utf-8"))
    next(row for row in doc["appearances"] if row["appearanceId"] == "light-exit-green")["emission"] = emission
    (tmp_path / "appearances.json").write_bytes(json.dumps(doc).encode("utf-8"))
    assert load_library(str(tmp_path))["appearances"]["light-exit-green"]["emission"] == emission


def test_a_use_of_a_light_finish_sets_its_own_pattern_and_sage_is_told_how():
    # The R03 case (main session, 2026-11-01): a stack light's red lamp should blink. The part takes the red finish
    # with its own pattern, instead of borrowing the blinking blue finish and recoloring it.
    red = {"key": "p:stack/red%20lamp#0", "appearanceId": "light-stack-red", "pattern": "blink", "periodSeconds": 1}
    doc = apply(layout(), {"op": "set_component_materials", "placementId": "pl-0",
                           "materials": {"representation": "overview", "overrides": [red]}})
    assert doc["placements"][0]["componentMaterials"]["overrides"] == [red]
    validate_layout(doc)
    # The same on a whole fitting, steady on a blinking finish, and in a custom finish.
    doc = apply(doc, set_appearance(["pl-1"], {"appearanceId": "light-beacon-amber", "pattern": "steady"}),
                custom({"appearanceId": "custom-red-strobe", "label": "Red strobe", "baseAppearanceId": "light-stack-red",
                        "pattern": "strobe", "periodSeconds": 0.5}),
                set_appearance(["pl-2"], {"appearanceId": "custom-red-strobe"}))
    assert doc["placements"][1]["appearance"] == {"appearanceId": "light-beacon-amber", "pattern": "steady"}
    assert doc["extensions"]["facilityAppearances"]["custom"][0]["pattern"] == "strobe"
    validate_layout(doc)
    # The schema Sage writes against takes it, and the tool text gives the example.
    from jsonschema import Draft202012Validator
    from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
    from ai_inspector.codex_runtime.library_tools import list_library, tool_specs
    schema = operation_batch_schema()
    operation = {"op": "set_component_materials", "placementId": "pl-0", "visualSha256": "a" * 64,
                 "materials": {"representation": "overview", "overrides": [red]}}
    assert not list(Draft202012Validator(schema).iter_errors({"operations": [operation]}))
    operation["materials"]["overrides"] = [dict(red, pattern="pulse")]
    assert list(Draft202012Validator(schema).iter_errors({"operations": [operation]}))
    variant = next(v for v in schema["properties"]["operations"]["items"]["oneOf"]
                   if v["properties"]["op"].get("const") == "set_component_materials")
    assert "light-stack-red" in variant["description"] and "pattern: 'blink'" in variant["description"]
    assert "add pattern and periodSeconds" in tool_specs()[0]["description"]
    assert "pattern steady|blink|strobe|rotate" in list_library({"kind": "appearances"})["adjustments"]


def test_a_light_may_cycle_through_colors_and_sage_is_told_how():
    """Colour-changing accent lighting (the user's game room, 2026-11-02): a Lights finish eases through a list of
    colors, one loop per periodSeconds (2 to 60 s), or through the default palette without one."""
    from ai_inspector.facility_layout import appearance_library as aplib
    strip = {"key": "p:strip/led#0", "appearanceId": "light-cool-white-led", "pattern": "cycle", "periodSeconds": 20,
             "cycleColors": ["#8A4DFF", "#00d5ff", "#ff3dce"]}
    doc = apply(layout(), {"op": "set_component_materials", "placementId": "pl-0",
                           "materials": {"representation": "overview", "overrides": [strip]}})
    assert doc["placements"][0]["componentMaterials"]["overrides"] == [
        dict(strip, cycleColors=["#8a4dff", "#00d5ff", "#ff3dce"])], "colors saved in lower case"
    doc = apply(doc, set_appearance(["pl-1"], {"appearanceId": "light-warm-white", "pattern": "cycle",
                                               "periodSeconds": 60}),
                custom({"appearanceId": "custom-party", "label": "Party", "baseAppearanceId": "light-cool-white-led",
                        "pattern": "cycle", "periodSeconds": 2, "cycleColors": ["#ff0000"] * 8}),
                set_appearance(["pl-2"], {"appearanceId": "custom-party"}))
    assert doc["placements"][1]["appearance"] == {"appearanceId": "light-warm-white", "pattern": "cycle",
                                                  "periodSeconds": 60}, "no colors: the default palette"
    assert doc["extensions"]["facilityAppearances"]["custom"][0]["cycleColors"] == ["#ff0000"] * 8
    validate_layout(doc)
    # A use may stop a cycle with another pattern, and the 3D view keeps the same default palette.
    doc = apply(doc, set_appearance(["pl-2"], {"appearanceId": "custom-party", "pattern": "blink", "periodSeconds": 1}))
    assert doc["placements"][2]["appearance"]["pattern"] == "blink"
    finishes_js = (Path(__file__).resolve().parents[1] / "static/facility_layout_finishes.js").read_text(encoding="utf-8")
    palette = ", ".join(f"'{color}'" for color in aplib.DEFAULT_CYCLE_COLORS)
    assert f"DEFAULT_CYCLE_COLORS = Object.freeze([{palette}])" in finishes_js
    # The schema Sage writes against takes it, refuses a bad list, and the tool text says how.
    from jsonschema import Draft202012Validator
    from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
    from ai_inspector.codex_runtime.library_tools import list_library, tool_specs
    schema = operation_batch_schema()
    operation = {"op": "set_component_materials", "placementId": "pl-0", "visualSha256": "a" * 64,
                 "materials": {"representation": "overview", "overrides": [strip]}}
    assert not list(Draft202012Validator(schema).iter_errors({"operations": [operation]}))
    for bad in (["#ff0000"], ["#ff0000"] * 9, ["#ff0000", "red"]):
        operation["materials"]["overrides"] = [dict(strip, cycleColors=bad)]
        assert list(Draft202012Validator(schema).iter_errors({"operations": [operation]})), bad
    whole = {"op": "set_appearance", "placementIds": ["pl-0"], "appearance": {
        "appearanceId": "light-cool-white-led", "pattern": "cycle", "periodSeconds": 30}}
    assert not list(Draft202012Validator(schema).iter_errors({"operations": [whole]}))
    variant = next(v for v in schema["properties"]["operations"]["items"]["oneOf"]
                   if v["properties"]["op"].get("const") == "set_component_materials")
    assert "pattern: 'cycle'" in variant["description"] and "cycleColors" in variant["description"]
    assert "add pattern cycle with periodSeconds (2-60 s per loop) and cycleColors" in tool_specs()[0]["description"]
    assert "or cycle with periodSeconds 2-60 and cycleColors" in list_library({"kind": "appearances"})["adjustments"]


@pytest.mark.parametrize("override, message", [
    ({"appearanceId": "light-stack-red", "pattern": "cycle"}, "needs periodSeconds"),
    ({"appearanceId": "light-stack-red", "pattern": "cycle", "periodSeconds": 1}, "between 2 and 60"),
    ({"appearanceId": "light-stack-red", "pattern": "cycle", "periodSeconds": 61}, "between 2 and 60"),
    ({"appearanceId": "light-stack-red", "pattern": "blink", "periodSeconds": 20}, "between 0.5 and 10"),
    ({"appearanceId": "light-stack-red", "pattern": "blink", "periodSeconds": 1, "cycleColors": ["#ff0000", "#0000ff"]},
     "cycleColors goes with pattern cycle"),
    ({"appearanceId": "light-stack-red", "cycleColors": ["#ff0000", "#0000ff"]}, "cycleColors goes with pattern cycle"),
    ({"appearanceId": "light-stack-red", "pattern": "cycle", "periodSeconds": 20, "cycleColors": ["#ff0000"]},
     "2 to 8 colors"),
    ({"appearanceId": "light-stack-red", "pattern": "cycle", "periodSeconds": 20, "cycleColors": ["#ff0000"] * 9},
     "2 to 8 colors"),
    ({"appearanceId": "light-stack-red", "pattern": "cycle", "periodSeconds": 20, "cycleColors": "#ff0000"},
     "2 to 8 colors"),
    ({"appearanceId": "light-stack-red", "pattern": "cycle", "periodSeconds": 20, "cycleColors": ["#ff0000", "blue"]},
     "six-digit hex color"),
    ({"appearanceId": "paint-machine-gray", "pattern": "cycle", "periodSeconds": 20}, "only on a Lights finish"),
    ({"appearanceId": "light-stack-red", "periodSeconds": 1}, "goes with a pattern"),
    ({"appearanceId": "light-stack-red", "pattern": "steady", "periodSeconds": 1}, "no periodSeconds"),
    ({"appearanceId": "light-stack-red", "pattern": "blink"}, "needs periodSeconds"),
    ({"appearanceId": "light-stack-red", "pattern": "pulse", "periodSeconds": 1}, "pattern must be"),
    ({"appearanceId": "light-stack-red", "pattern": "blink", "periodSeconds": 0.2}, "between 0.5 and 10"),
    ({"appearanceId": "paint-machine-gray", "pattern": "blink", "periodSeconds": 1}, "only on a Lights finish"),
])
def test_a_pattern_needs_a_light_and_its_period(override, message):
    with pytest.raises(FacilityLayoutError, match=message):
        apply(layout(), {"op": "set_component_materials", "placementId": "pl-0", "materials": {
            "representation": "overview", "overrides": [dict(override, key="p:stack/red#0")]}})
    with pytest.raises(FacilityLayoutError, match=message):
        apply(layout(), set_appearance(["pl-0"], override))
    with pytest.raises(FacilityLayoutError, match=message):
        apply(layout(), custom(dict({k: v for k, v in override.items() if k != "appearanceId"},
                                    appearanceId="custom-x", label="x", baseAppearanceId=override["appearanceId"])))


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
    # The lights switch is saved with the scene, and Sage can set it.
    dark = apply(layout(), {"op": "set_scene", "scene": {"version": 1, "sceneId": "machine-shop", "adjustments": {"lights": False}}})
    assert dark["extensions"]["facilityScene"]["adjustments"] == {"lights": False}
    validate_layout(dark)
    from jsonschema import Draft202012Validator
    from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
    errors = Draft202012Validator(operation_batch_schema()).iter_errors({"operations": [
        {"op": "set_scene", "scene": {"version": 1, "sceneId": "machine-shop", "adjustments": {"lights": False}}}]})
    assert not list(errors)


def test_a_scene_change_without_a_scene_id_keeps_the_saved_scene():
    # Sage, 2026-10-31: "Turn the lights off" while in Evening came back as Classic. It stays Evening now.
    evening = apply(layout(), {"op": "set_scene", "scene": {"version": 1, "sceneId": "evening",
                                                            "adjustments": {"exposure": 0.9, "lights": True}}})
    dark = apply(evening, {"op": "set_scene", "scene": {"version": 1, "adjustments": {"lights": False}}})
    assert dark["extensions"]["facilityScene"] == {"version": 1, "sceneId": "evening",
                                                   "adjustments": {"exposure": 0.9, "lights": False}}
    validate_layout(dark)
    assert apply(dark, {"op": "set_scene", "scene": {"version": 1}})["extensions"] == dark["extensions"]
    # With no saved scene the change applies to Classic; a sceneId still replaces the scene and its adjustments.
    assert apply(layout(), {"op": "set_scene", "scene": {"version": 1, "adjustments": {"lights": False}}})[
        "extensions"]["facilityScene"] == {"version": 1, "sceneId": "classic", "adjustments": {"lights": False}}
    assert apply(dark, {"op": "set_scene", "scene": {"version": 1, "sceneId": "warehouse"}})["extensions"][
        "facilityScene"] == {"version": 1, "sceneId": "warehouse"}
    with pytest.raises(FacilityLayoutError):
        apply(evening, {"op": "set_scene", "scene": {"version": 1, "adjustments": {"lights": "off"}}})
    from jsonschema import Draft202012Validator
    from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
    assert not list(Draft202012Validator(operation_batch_schema()).iter_errors({"operations": [
        {"op": "set_scene", "scene": {"version": 1, "adjustments": {"lights": False}}}]}))


def test_sage_naming_the_current_scene_keeps_its_saved_adjustments(monkeypatch):
    # The main session, 2026-11-01: "Switch this layout to the evening scene with a glow halo around the lights" on an
    # Evening layout with light areas came back without them, as a sceneId replaces the scene. For Sage, naming the
    # scene the layout already has is not a switch.
    from ai_inspector.facility_layout.operations import keep_current_scene
    areas = {"mode": "only", "areas": [{"rectangle": {"minX": 0, "minZ": 0, "maxX": 10, "maxZ": 10}}]}
    evening = apply(layout(), {"op": "set_scene", "scene": {"version": 1, "sceneId": "evening",
                                                            "adjustments": {"lightAreas": areas}}})
    halo = {"op": "set_scene", "scene": {"version": 1, "sceneId": "evening", "adjustments": {"glowHalo": True}}}
    [kept] = keep_current_scene([halo], evening)
    assert kept == {"op": "set_scene", "scene": {"version": 1, "adjustments": {"glowHalo": True}}}
    assert apply(evening, kept)["extensions"]["facilityScene"] == {
        "version": 1, "sceneId": "evening", "adjustments": {"lightAreas": areas, "glowHalo": True}}
    # Another scene is a switch, null and then the scene starts it afresh, and with no saved scene nothing changes.
    warehouse = {"op": "set_scene", "scene": {"version": 1, "sceneId": "warehouse"}}
    assert keep_current_scene([warehouse], evening) == [warehouse]
    afresh = [{"op": "set_scene", "scene": None}, halo]
    assert keep_current_scene(afresh, evening) == afresh
    assert keep_current_scene([halo], layout()) == [halo]
    # Only Sage's previews come here: the operation itself (the Scenes pane) still replaces the scene.
    assert apply(evening, halo)["extensions"]["facilityScene"] == {
        "version": 1, "sceneId": "evening", "adjustments": {"glowHalo": True}}
    # Sage's gateway applies it before staging, and the tool text says so.
    from types import SimpleNamespace
    from ai_inspector.codex_runtime import assisted_tools, facility_tools
    from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
    seen = {}

    def staged(*_args, operations, **_kwargs):
        seen["operations"] = operations
        raise RuntimeError("staged")

    monkeypatch.setattr(facility_tools, "read_bound_layout", lambda *_: {"layout": evening})
    monkeypatch.setattr(assisted_tools, "create", staged)
    gateway = object.__new__(assisted_tools.FacilityEditGateway)
    gateway.runtime, gateway.principal = SimpleNamespace(service=None), None
    gateway.reference = {"siteId": "site", "layoutId": "layout", "revision": "r1"}
    gateway.edit_mode = "direct"
    with pytest.raises(RuntimeError, match="staged"):
        gateway._read_data("preview_facility_operations", {"operations": [halo]})
    assert seen["operations"] == [kept]
    variant = next(v for v in operation_batch_schema()["properties"]["operations"]["items"]["oneOf"]
                   if v["properties"]["op"].get("const") == "set_scene")
    assert "Naming the scene the layout already has is not a switch" in variant["description"]


def test_the_glow_halo_is_saved_with_the_scene_and_sage_can_turn_it_on():
    # Lighting L6: off unless the scene says so; the view draws it only in a scene with floor light pools.
    halo = apply(layout(), {"op": "set_scene", "scene": {"version": 1, "sceneId": "evening",
                                                         "adjustments": {"glowHalo": True}}})
    assert halo["extensions"]["facilityScene"] == {"version": 1, "sceneId": "evening", "adjustments": {"glowHalo": True}}
    validate_layout(halo)
    # "Turn the glow off" keeps Evening and its other adjustments.
    plain = apply(halo, {"op": "set_scene", "scene": {"version": 1, "adjustments": {"glowHalo": False}}})
    assert plain["extensions"]["facilityScene"] == {"version": 1, "sceneId": "evening",
                                                    "adjustments": {"glowHalo": False}}
    from jsonschema import Draft202012Validator
    from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
    schema = operation_batch_schema()
    assert not list(Draft202012Validator(schema).iter_errors({"operations": [
        {"op": "set_scene", "scene": {"version": 1, "sceneId": "evening", "adjustments": {"glowHalo": True}}}]}))
    assert list(Draft202012Validator(schema).iter_errors({"operations": [
        {"op": "set_scene", "scene": {"version": 1, "adjustments": {"glowHalo": "on"}}}]}))
    set_scene = next(v for v in schema["properties"]["operations"]["items"]["oneOf"]
                     if v["properties"]["op"].get("const") == "set_scene")
    assert "glowHalo" in set_scene["description"] and "evening" in set_scene["description"]
    # Sage's scene list says which scenes have floor pools, and so can show the halo.
    scenes = {row["sceneId"]: row for row in library_summary("scenes")}
    assert scenes["evening"]["lightPools"] is True
    assert all("lightPools" not in row for key, row in scenes.items() if key != "evening")


# General lights per area (L7) --------------------------------------------------------

def floors(*ids):
    doc = layout()
    doc.setdefault("extensions", {})["facilityPlan"] = default_plan_settings()
    return apply(doc, *({"op": "upsert_floor_surface", "surface": {"surfaceId": surface, "label": surface[3:].title(),
        "boundary": [{"x": x, "z": 20}, {"x": x + 4, "z": 20}, {"x": x + 4, "z": 24}, {"x": x, "z": 24}],
        "elevation": 0, "material": "concrete", "color": "#8A8F94", "roughness": 0.8}}
        for x, surface in zip(range(0, 40, 5), ids)))


def test_light_areas_are_saved_with_the_scene_and_name_floor_areas_of_this_layout():
    doc = floors("fs-receiving", "fs-gym")
    areas = {"mode": "only", "areas": [{"surfaceId": "fs-receiving"},
                                       {"rectangle": {"minX": 10.12345, "minZ": 2, "maxX": 14, "maxZ": 3.5}}]}
    lit = apply(doc, {"op": "set_scene", "scene": {"version": 1, "sceneId": "evening",
                                                   "adjustments": {"lightAreas": areas}}})
    saved = lit["extensions"]["facilityScene"]["adjustments"]["lightAreas"]
    assert saved == {"mode": "only", "areas": [{"surfaceId": "fs-receiving"},
                                               {"rectangle": {"minX": 10.123, "minZ": 2, "maxX": 14, "maxZ": 3.5}}]}
    validate_layout(lit)
    with pytest.raises(FacilityLayoutError, match="Unknown floor area 'fs-office'"):
        apply(doc, {"op": "set_scene", "scene": {"version": 1, "adjustments": {"lightAreas": {
            "mode": "except", "areas": [{"surfaceId": "fs-office"}]}}}})
    # A floor area deleted later lights nothing, and a lights-only change keeps the saved areas.
    gone = apply(lit, {"op": "delete_floor_surface", "surfaceId": "fs-receiving"})
    dark = apply(gone, {"op": "set_scene", "scene": {"version": 1, "adjustments": {"lights": False}}})
    assert dark["extensions"]["facilityScene"] == {"version": 1, "sceneId": "evening",
                                                   "adjustments": {"lightAreas": saved, "lights": False}}
    # Everywhere except nothing: general lights on everywhere again, still in Evening.
    again = apply(dark, {"op": "set_scene", "scene": {"version": 1, "adjustments": {"lightAreas": {
        "mode": "except", "areas": []}}}})
    assert again["extensions"]["facilityScene"]["adjustments"] == {"lightAreas": {"mode": "except", "areas": []},
                                                                   "lights": False}
    from jsonschema import Draft202012Validator
    from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
    assert not list(Draft202012Validator(operation_batch_schema()).iter_errors({"operations": [
        {"op": "set_scene", "scene": {"version": 1, "adjustments": {"lightAreas": areas}}}]}))


@pytest.mark.parametrize("light_areas", [
    {"mode": "on", "areas": []},
    {"mode": "only"},
    {"mode": "only", "areas": {"surfaceId": "fs-gym"}},
    {"mode": "only", "areas": [{"surfaceId": "gym"}]},
    {"mode": "only", "areas": [{"surfaceId": "fs-gym", "rectangle": {"minX": 0, "minZ": 0, "maxX": 1, "maxZ": 1}}]},
    {"mode": "only", "areas": [{"rectangle": {"minX": 0, "minZ": 0, "maxX": 1}}]},
    {"mode": "only", "areas": [{"rectangle": {"minX": 0, "minZ": 0, "maxX": 0.05, "maxZ": 1}}]},
    {"mode": "only", "areas": [{"rectangle": {"minX": 0, "minZ": 0, "maxX": "1", "maxZ": 1}}]},
    {"mode": "only", "areas": [{"surfaceId": "fs-gym"}, {"surfaceId": "fs-gym"}]},
    {"mode": "only", "areas": [{"rectangle": {"minX": i, "minZ": 0, "maxX": i + 1, "maxZ": 1}} for i in range(65)]},
])
def test_invalid_light_areas_are_rejected(light_areas):
    with pytest.raises(FacilityLayoutError):
        apply(floors("fs-gym"), {"op": "set_scene", "scene": {"version": 1, "sceneId": "evening",
                                                              "adjustments": {"lightAreas": light_areas}}})


@pytest.mark.parametrize("scene", [
    {"version": 1, "sceneId": "moon-base"},
    {"version": 2, "sceneId": "classic"},
    {"version": 1, "sceneId": "classic", "adjustments": {"exposure": 9}},
    {"version": 1, "sceneId": "classic", "adjustments": {"fog": 1}},
    {"version": 1, "sceneId": "classic", "adjustments": {"shadows": "yes"}},
    {"version": 1, "sceneId": "classic", "adjustments": {"lights": "off"}},
    {"version": 1, "sceneId": "classic", "adjustments": {"lights": 0}},
    {"version": 1, "sceneId": "evening", "adjustments": {"glowHalo": "on"}},
    {"version": 1, "sceneId": "evening", "adjustments": {"glowHalo": 1}},
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
