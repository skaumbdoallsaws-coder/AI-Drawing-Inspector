"""Lighting L5 and L8: the Factory 02 light models (tools/factory02_light_models.py) and the re-runnable Factory 02
pass (tools/light_factory02.py), on a temporary project root and a small made-up layout."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import struct

import numpy as np
import pytest

from ai_inspector.facility_layout.appearance_library import load_library
from ai_inspector.facility_layout.host import build_private_local_asset_catalog
from ai_inspector.facility_layout.operations import apply_facility_layout_operations, create_layout_document
from ai_inspector.facility_layout.spatial import _quaternion, _rotate_vector, diagnose_layout
from tools import factory02_light_models as models
from tools import light_factory02 as light_pass

LAMP_PARTS = {"green lamp", "amber lamp", "red lamp", "beacon lens"}
LED_LENS = "led lens"   # L8: the outdoor lights' lens, which faces down on purpose (it throws a beam and a pool)
# The Factory 02 models the pass mounts lights on, with their real sizes (width, depth, height) and footprints.
# generated/ is not in the repo, so the test gives them as stand-ins without a visual.
SUPPORTS = {
    light_pass.ROBOT: ("Automation", (1.8980626165866852, 3.0449138283729553, 2.143772125244142), None),
    light_pass.GUARD: ("Safety", (0.045470401644706726, 1.4500000476837158, 2.0409998893737793), None),
    "asset-forklift-2610x2264x986-minimum-height-green": (
        "Material Handling", (2.648569941520691, 0.9861500263214111, 2.277822494506836), None),
    light_pass.DOCK: ("Building Structures", (4.496, 1.0426, 10.0), [
        [(-2.247999906539917, -0.1213), (2.247999906539917, -0.1213), (2.247999906539917, 0.1237),
         (-2.247999906539917, 0.1237)],
        [(-1.92, 0.1237), (1.92, 0.1237), (1.92, 0.5212792754173279), (-1.92, 0.5212792754173279)]]),
    light_pass.ROW: ("Building Structures", (294.388, 0.388, 1.005), None),
    light_pass.WHEEL_STOP: ("Facilities", (1.6, 0.16, 0.14), None),
}
COMPACT = "asset-forklift-2610x2264x986-minimum-height-green"
GUARD_HALF = SUPPORTS[light_pass.GUARD][1][1] / 2
HOUSING = {"key": "p:high-bay-light-row-294m/housing#0", "color": "#30343a", "roughness": 0.5, "metalness": 0.4}


def _glb(raw):
    magic, version, length = struct.unpack_from("<4sII", raw, 0)
    assert (magic, version, length) == (b"glTF", 2, len(raw))
    json_length, kind = struct.unpack_from("<I4s", raw, 12)
    assert kind == b"JSON"
    doc = json.loads(raw[20:20 + json_length])
    bin_length, kind = struct.unpack_from("<I4s", raw, 20 + json_length)
    assert kind == b"BIN\0" and 28 + json_length + bin_length == len(raw)
    return doc, raw[28 + json_length:]


def _parts(raw):
    """The model's root node and {part name: (positions, normals, triangles, material)}."""
    doc, data = _glb(raw)

    def array(index, dtype, width):
        accessor = doc["accessors"][index]
        offset = doc["bufferViews"][accessor["bufferView"]]["byteOffset"]
        return np.frombuffer(data, dtype=dtype, count=accessor["count"] * width, offset=offset).reshape(-1, width)

    parts = {}
    for node in doc["nodes"][1:]:
        primitive = doc["meshes"][node["mesh"]]["primitives"][0]
        parts[node["name"]] = (array(primitive["attributes"]["POSITION"], "<f4", 3),
                               array(primitive["attributes"]["NORMAL"], "<f4", 3),
                               array(primitive["indices"], "<u2", 1).reshape(-1, 3),
                               doc["materials"][primitive["material"]])
    return doc["nodes"][0], parts


def _faces(positions, triangles):
    a, b, c = (positions[triangles[:, i]].astype(float) for i in range(3))
    return np.cross(b - a, c - a)


@pytest.mark.parametrize("model", models.MODELS, ids=lambda model: model["assetId"])
def test_each_light_model_is_named_parts_with_their_own_finishes_and_outward_faces(model):
    root, parts = _parts(models.build(model))   # build() also checks the bounds fill the catalog dimensions
    assert root["name"] == model["root"] and root["children"] == list(range(1, len(parts) + 1))
    assert list(parts) == [name for name, _, _ in model["parts"]()]
    for name, (positions, normals, triangles, material) in parts.items():
        assert material["name"] == name
        lit, groups = model.get("defaultFinishes", {}), model.get("finishGroups", {})
        assert material["extras"] == {"facilityAuthoredFinish": True, "facilityMaterialRole": name,
                                      **({"facilityDefaultFinish": lit[name]} if name in lit else {}),
                                      **({"facilityFinishGroup": groups[name]} if name in groups else {})}
        assert triangles.max() < len(positions)
        faces = _faces(positions, triangles)
        agree = np.einsum("ij,ij->i", faces, normals[triangles].astype(float).mean(axis=1))
        assert np.all((agree > 0) | (np.linalg.norm(faces, axis=1) < 1e-12)), name
    keys = [key for key in (*models.STACK_LAMP_KEYS.values(), *models.BEACON_LENS_KEYS.values(),
                            *models.LED_LENS_KEYS.values())
            if key.startswith("p:" + model["root"] + "/")]
    assert keys, "each model has a lamp part a Lights finish goes on"
    for key in keys:
        assert key.split("/", 1)[1].split("#")[0].replace("%20", " ") in (LAMP_PARTS | {LED_LENS}) & set(parts)
    entry = models.catalog_entry(model)
    assert entry["dimensions"] == model["dimensions"] and entry["sourceToCanonical"] == models.IDENTITY
    for polygon in entry.get("footprintPolygons", []):
        assert all(abs(p["x"]) <= model["dimensions"]["width"] / 2 and abs(p["z"]) <= model["dimensions"]["depth"] / 2
                   for p in polygon)


def test_light_fittings_come_lit_and_a_stack_light_comes_green():
    """FIX 3a: the lens of the pole light, the wall light and both beacons names its Lights finish in the model, so a
    placed light glows with no finish step. A stack light comes with its green lamp on, steady; its amber and red
    lamps start unlit. Its three lamps are one finish group: one lamp shows the cell's state, so a finish of its own on
    any of them turns the green default off. The defaults are in the GLB, not the catalog entry, so the asset
    revisions (and the lights already placed) stay."""
    appearances = load_library()["appearances"]
    lit, groups = {}, {}
    for model in models.MODELS:
        _, parts = _parts(models.build(model))
        for name, (_, _, _, material) in parts.items():
            if "facilityDefaultFinish" in material["extras"]:
                lit[(model["assetId"], name)] = material["extras"]["facilityDefaultFinish"]
            if "facilityFinishGroup" in material["extras"]:
                groups[(model["assetId"], name)] = material["extras"]["facilityFinishGroup"]
        assert "defaultFinishes" not in json.dumps(models.catalog_entry(model))
        assert "finishGroups" not in json.dumps(models.catalog_entry(model))
    assert lit == {(models.BEACON, "beacon lens"): "light-beacon-amber",
                   (models.WALL_BEACON, "beacon lens"): "light-beacon-amber",
                   (models.POLE_LIGHT, "led lens"): "light-pole-led",
                   (models.WALL_LIGHT, "led lens"): "light-wall-led",
                   (models.STACK_LIGHT, "green lamp"): "light-stack-green"}
    assert groups == {(models.STACK_LIGHT, lamp): "stack lamps" for lamp in ("green lamp", "amber lamp", "red lamp")}
    for appearance_id in lit.values():
        assert appearances[appearance_id]["category"] == "lights"
    assert "pattern" not in appearances["light-stack-green"]["emission"], "steady"


def test_lamp_parts_have_no_downward_faces_so_they_throw_no_floor_pool():
    """The 3D view treats a glowing part as a downward lamp (with a floor pool) only when a fifth of its surface faces
    down. Stack lamps are sides only and a beacon lens is a side and a dome: none faces down."""
    seen = set()
    for model in models.MODELS:
        for name, (positions, _, triangles, _) in _parts(models.build(model))[1].items():
            if name in LAMP_PARTS:
                faces = _faces(positions, triangles)
                units = faces / np.linalg.norm(faces, axis=1, keepdims=True)
                assert units[:, 1].min() > -1e-3, (model["assetId"], name)
                seen.add(name)
    assert seen == LAMP_PARTS


def test_outdoor_led_lenses_face_down_so_the_view_aims_their_beams():
    """L8: the 3D view takes a part as a lamp when a fifth of it faces down (normal y below -0.7) and aims its beam
    along those faces. The pole light's lens is all one face looking straight down from 7.85 m; the wall light's
    looks down and 30 degrees out from the wall (+Z, away from its back plate)."""
    tilt = math.radians(models.WALL_LIGHT_TILT)
    for asset_id, aim, low in ((models.POLE_LIGHT, (0.0, -1.0, 0.0), models.POLE_HEIGHT - 0.15),
                               (models.WALL_LIGHT, (0.0, -math.cos(tilt), math.sin(tilt)), 0.04)):
        model = next(m for m in models.MODELS if m["assetId"] == asset_id)
        positions, _, triangles, material = _parts(models.build(model))[1][LED_LENS]
        faces = _faces(positions, triangles)
        assert np.allclose(faces / np.linalg.norm(faces, axis=1, keepdims=True), aim, atol=1e-5), asset_id
        assert positions[:, 1].min() == pytest.approx(low, abs=1e-6)
        assert material["name"] == LED_LENS
        assert models.LED_LENS_KEYS[asset_id] == "p:" + model["root"] + "/led%20lens#0"


def _project(tmp_path):
    """A project root whose asset manifest has the support stand-ins (no visuals)."""
    assets = []
    for asset_id, (category, (width, depth, height), footprint) in SUPPORTS.items():
        entry = {"artifact": f"generated/stand-ins/{asset_id}.glb", "assetId": asset_id, "category": category,
                 "description": "Test stand-in.", "dimensions": {"width": width, "depth": depth, "height": height},
                 "displayName": asset_id, "sourceToCanonical": list(models.IDENTITY), "tags": []}
        if footprint:
            entry["footprintPolygons"] = [[{"x": x, "z": z} for x, z in polygon] for polygon in footprint]
        assets.append(entry)
    manifest = tmp_path / models.CATALOG
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(json.dumps({"assets": assets, "schemaVersion": 1, "summary": {"total": len(assets)}},
                                    separators=(",", ":"), sort_keys=True).encode("ascii"))
    return tmp_path


def test_install_adds_the_models_once_keeps_the_manifest_layout_and_the_host_reads_them(tmp_path):
    root = _project(tmp_path)
    first = models.install(root)
    assert sorted(first["modelsWritten"]) == sorted(models.FOLDER + "/" + m["file"] for m in models.MODELS)
    assert first["catalogChanged"] is True
    written = (root / models.CATALOG).read_bytes()
    assert models.install(root) == {"modelsWritten": [], "catalogChanged": False, "assetIds": first["assetIds"]}
    assert (root / models.CATALOG).read_bytes() == written
    manifest = json.loads(written)
    assert json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("ascii") == written
    assert manifest["summary"]["total"] == len(manifest["assets"]) == len(SUPPORTS) + len(models.MODELS)
    catalog = {entry["assetId"]: entry for entry in build_private_local_asset_catalog(root)}
    for model in models.MODELS:
        entry = catalog[model["assetId"]]
        assert entry["privateLocalVisual"]["available"] is True
        assert entry["overview"]["path"] == "/" + models.FOLDER + "/" + model["file"]
        aabb = entry["definition"]["geometry"]["aabb"]
        assert aabb["maximum"]["y"] == pytest.approx(model["dimensions"]["height"])
    assert catalog[models.STACK_LIGHT]["definition"]["geometry"]["footprintPolygons"] == [
        [{"x": -0.02, "z": -0.02}, {"x": 0.02, "z": -0.02}, {"x": 0.02, "z": 0.02}, {"x": -0.02, "z": 0.02}]]


def _layout(catalog):
    layout = create_layout_document(
        layout_id="fl-l5-test", display_name="L5 test", association={"siteId": "site-local", "areaId": "main"},
        coordinate_frame={"units": "m", "handedness": "right", "upAxis": "+Y", "floorAxes": ["+X", "+Z"],
                          "datumId": "origin-a", "floorElevation": 0},
        source_shell_ref={"shellId": "shell-a", "shellRevision": "d" * 64, "coordinateFrameFingerprint": "e" * 64},
        policy_set_ref={"policySetId": "policy-a", "policySetRevision": "f" * 64},
        created_at="2026-10-31T00:00:00Z")

    def place(placement_id, asset_id, x, z, label, y=0.0, yaw=0.0):
        half = math.radians(yaw) / 2
        return {"op": "place_asset", "placement": {
            "placementId": placement_id, "assetId": asset_id,
            "assetDefinitionRevision": catalog[asset_id]["assetDefinitionRevision"],
            "transform": {"position": {"x": x, "y": y, "z": z},
                          "quaternion": {"x": 0.0, "y": math.sin(half), "z": 0.0, "w": math.cos(half)}, "scale": 1},
            "positionMode": "manual", "snapRelationship": None,
            "metadata": {"inputMethod": "independent-authoring", "instanceLabel": label}}}

    ops = []
    for cell, x in (("R06", 10.0), ("R07", 20.0)):
        ops.append(place(f"pl-{cell.lower()}-robot", light_pass.ROBOT, x, 10.0, f"{cell} robot"))
        # The front guard row runs along +Z: two panels, a 2 m entrance, two panels (5 cm apart).
        for n, z in enumerate((2.0, 3.5, 7.0, 8.5)):
            ops.append(place(f"pl-{cell.lower()}-front-{n}", light_pass.GUARD, x - 3.0, z, f"{cell} front guard"))
    ops.append(place("pl-receiving-forklift", COMPACT, 30.0, 30.0, "Receiving forklift"))
    ops.append(place("pl-dispatch-forklift", "asset-forklift", 40.0, 30.0, "Dispatch forklift", yaw=90.0))
    ops.append(place("pl-factory02-support-dock-door-01", light_pass.DOCK, 0.0, 20.0, "Dock door S1 - open", yaw=90.0))
    ops.append(place("pl-light-row-01", light_pass.ROW, 150.0, 30.0, "Light row 1", y=9.0))
    # L8: a car park (two rows of wheel stops head to head, 1.8 m apart, and a row facing elsewhere) and a truck yard
    # sunk 1.35 m along the -X side.
    for row, z in (("a", 50.0), ("b", 51.8), ("c", 40.0)):
        for n, x in enumerate((46.0, 48.8, 51.6, 54.4)):
            ops.append(place(f"pl-stop-{row}{n}", light_pass.WHEEL_STOP, x, z, f"Wheel stop {row}{n}"))
    ops.append({"op": "set_ground", "ground": {"schemaVersion": 1, "surfaces": [
        {"surfaceId": "floor", "minX": -1.0, "maxX": 60.0, "minZ": 0.0, "maxZ": 60.0, "startElevation": 0.0,
         "endElevation": 0.0, "slopeAxis": "x", "color": "#8a8f94"},
        {"surfaceId": "yard", "minX": -31.0, "maxX": -1.0, "minZ": 0.0, "maxZ": 60.0, "startElevation": -1.35,
         "endElevation": -1.35, "slopeAxis": "x", "color": "#3d4247"}]}})
    ops.append({"op": "set_component_materials", "placementId": "pl-light-row-01",
                "materials": {"representation": "overview", "overrides": [HOUSING]}})
    return apply_facility_layout_operations(layout, ops)["document"]


def _steps(ops):
    return [(op["op"], op.get("placementId") or op["placement"]["placementId"]) for op in ops]


def test_the_pass_places_each_light_once_keeps_the_findings_and_follows_changes(tmp_path):
    root = _project(tmp_path)
    models.install(root)
    entries = build_private_local_asset_catalog(root)
    catalog = {entry["assetId"]: entry for entry in entries}
    layout = _layout(catalog)

    ops, summary = light_pass.light_operations(layout, catalog)
    assert summary["stackLights"] == ["pl-factory02-stack-light-r06", "pl-factory02-stack-light-r07"]
    assert summary["forkliftBeacons"] == ["pl-factory02-beacon-dispatch-forklift", "pl-factory02-beacon-receiving-forklift"]
    assert summary["dockBeacons"] == ["pl-factory02-beacon-dock-door-01"]
    assert (summary["lightRows"], summary["lightRowsSet"], summary["removed"]) == (1, 1, [])
    assert summary["carParkLights"] == ["pl-factory02-pole-light-car-park-01"]
    assert summary["yardLights"] == ["pl-factory02-pole-light-yard-01", "pl-factory02-pole-light-yard-02"]
    assert summary["dockLights"] == ["pl-factory02-dock-light-dock-door-01"]
    after = apply_facility_layout_operations(layout, ops)["document"]
    light_pass.audit(layout, after, ops)
    placed = {p["placementId"]: p for p in after["placements"]}

    row = placed["pl-light-row-01"]["componentMaterials"]
    assert [o["key"] for o in row["overrides"]] == [HOUSING["key"], light_pass.LENS_KEY]
    assert row["overrides"][1]["appearanceId"] == "light-cool-white-led"
    # A stack light stands on the top rail of the first panel after each entrance, at the end by the opening.
    for cell, lamp in (("r06", "amber"), ("r07", "green")):
        light = placed["pl-factory02-stack-light-" + cell]
        x = 7.0 if cell == "r06" else 17.0
        assert light["transform"]["position"] == pytest.approx(
            {"x": x, "y": SUPPORTS[light_pass.GUARD][1][2], "z": 7.0 - GUARD_HALF + light_pass.STACK_FOOT_MARGIN})
        assert light["snapRelationship"]["supportPlacementId"] == f"pl-{cell}-front-2"
        assert [(o["key"], o["appearanceId"]) for o in light["componentMaterials"]["overrides"]] == [
            (models.STACK_LAMP_KEYS[lamp], "light-stack-" + lamp)]
    beacon = placed["pl-factory02-beacon-receiving-forklift"]
    local = light_pass.FORKLIFT_ROOFS[COMPACT]
    assert beacon["transform"]["position"] == pytest.approx(
        {"x": 30.0 + local[0], "y": SUPPORTS[COMPACT][1][2], "z": 30.0 + local[1]})
    turned = placed["pl-factory02-beacon-dispatch-forklift"]["transform"]["position"]   # turned 90 degrees
    local = light_pass.FORKLIFT_ROOFS["asset-forklift"]
    assert (turned["x"], turned["z"]) == pytest.approx((40.0 + local[1], 30.0 - local[0]))
    dock = placed["pl-factory02-beacon-dock-door-01"]
    assert dock["positionMode"] == "locked" and dock["snapRelationship"] is None
    assert dock["transform"]["position"] == pytest.approx({"x": 0.2367, "y": 4.6, "z": 22.05})
    assert [o["appearanceId"] for o in dock["componentMaterials"]["overrides"]] == ["light-beacon-amber"]

    # L8: a pole light on the line between the head-to-head rows, mid-way along them; two along the yard's far edge,
    # on the yard; a light outside the dock door, its back 3 mm off the wall, facing out, 4.6 m up.
    lens = lambda placement: [(o["key"], o["appearanceId"]) for o in placement["componentMaterials"]["overrides"]]
    park = placed["pl-factory02-pole-light-car-park-01"]
    assert park["transform"]["position"] == pytest.approx({"x": 50.2, "y": 0.0, "z": 50.9})
    assert (park["positionMode"], park["metadata"]["instanceLabel"]) == ("locked", "Car park light 01")
    assert lens(park) == [(models.LED_LENS_KEYS[models.POLE_LIGHT], "light-pole-led")]
    for n, z in ((1, 15.0), (2, 45.0)):
        yard = placed[f"pl-factory02-pole-light-yard-0{n}"]
        assert yard["transform"]["position"] == pytest.approx({"x": -28.0, "y": -1.35, "z": z})
        assert lens(yard) == [(models.LED_LENS_KEYS[models.POLE_LIGHT], "light-pole-led")]
    light = placed["pl-factory02-dock-light-dock-door-01"]
    half = 0.125   # the wall light's half depth
    assert light["transform"]["position"] == pytest.approx({"x": -0.1213 - 0.003 - half, "y": 4.6, "z": 20.0})
    assert light["metadata"]["instanceLabel"] == "Dock light S1"
    out = _rotate_vector((0.0, 0.0, 1.0), _quaternion(light["transform"]["quaternion"]))
    assert out == pytest.approx((-1.0, 0.0, 0.0)), "its lens faces out of the building"
    assert light["transform"]["quaternion"]["w"] > 0
    assert lens(light) == [(models.LED_LENS_KEYS[models.WALL_LIGHT], "light-dock-led")]

    # The spatial check: no errors, the warnings as before, and new notes only about the lights.
    before_findings, after_findings = diagnose_layout(layout, entries), diagnose_layout(after, entries)
    assert [f for f in after_findings["findings"] if f["severity"] == "error"] == []
    own = {op["placement"]["placementId"] for op in ops if op["op"] == "place_asset"}
    compared, problems = light_pass.compare_findings(
        {"spatial": before_findings, "routing": {"findings": []}},
        {"spatial": after_findings, "routing": {"findings": []}}, own)
    assert problems == [] and compared["spatial"]["errorsAndWarningsUnchanged"]
    assert compared["spatial"]["addedNotes"]["surface_attachment_safety_unverified"] == 4

    # Run again: nothing to do. Move a forklift: only its beacon follows. Remove a cell: only its stack light goes.
    assert light_pass.light_operations(after, catalog)[0] == []
    moved = deepcopy(after)
    next(p for p in moved["placements"] if p["placementId"] == "pl-receiving-forklift")["transform"]["position"]["x"] = 32.0
    ops, _ = light_pass.light_operations(moved, catalog)
    assert _steps(ops) == [("delete_placement", "pl-factory02-beacon-receiving-forklift"),
                           ("place_asset", "pl-factory02-beacon-receiving-forklift"),
                           ("set_component_materials", "pl-factory02-beacon-receiving-forklift")]
    assert ops[1]["placement"]["transform"]["position"]["x"] == pytest.approx(32.0 + light_pass.FORKLIFT_ROOFS[COMPACT][0])
    without = deepcopy(after)
    without["placements"] = [p for p in without["placements"] if p["placementId"] != "pl-r07-robot"]
    assert _steps(light_pass.light_operations(without, catalog)[0]) == [
        ("delete_placement", "pl-factory02-stack-light-r07")]
    # A parking row taken away takes its strip's light along.
    unparked = deepcopy(after)
    unparked["placements"] = [p for p in unparked["placements"] if not p["placementId"].startswith("pl-stop-b")]
    assert _steps(light_pass.light_operations(unparked, catalog)[0]) == [
        ("delete_placement", "pl-factory02-pole-light-car-park-01")]
