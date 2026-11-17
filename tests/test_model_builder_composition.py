"""MB3 geometry/material composition with generated fixtures, run outside sandbox."""
from copy import deepcopy
from io import BytesIO

import numpy as np
from PIL import Image
import pytest

from ai_inspector.industrial_assets.model_builder.errors import ModelBuildError as HostError

from tests.model_builder_test_support import gltf, module, recipe, reference, shape
from tests.model_builder_composition_support import CatalogFixture, credit, cube_payload, edit_glb

kernel, protocol = module("build"), module("protocol")
Error = (module("errors").ModelBuildError, HostError)


def checked_result(built, appearance_ids=()):
    from ai_inspector.industrial_assets.primitives import verify
    result = protocol.make_result(built, {"categories": [built.recipe["category"]], "appearanceIds": list(appearance_ids)})
    protocol.validate_glb_metadata(gltf(built.glb), result, payload=built.glb)
    verify(built.glb, built.dimensions, base_height=built.recipe["hangHeight"])
    return result


def test_plain_pallet_include_preserves_size_names_mapping_and_no_surface_inheritance(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    pallet = kernel.build_model(reference("pallet-plain"))
    asset = fixtures.add("pallet", pallet.glb, dimensions=pallet.dimensions, surfaces=True)
    entry, inspected = fixtures.include(asset, name="pallet")
    built = fixtures.build(recipe(entry, size=pallet.dimensions))
    assert built.dimensions == pytest.approx(pallet.dimensions, abs=1e-6)
    assert {p.name for p in built.model.parts} == {"pallet: pallet boards", "pallet: pallet blocks"}
    result = checked_result(built)
    assert set(result["includes"][0]["partMap"]) == {p["key"] for p in inspected["parts"]}
    assert set(result["includes"][0]["partMap"].values()) == set(built.part_map["entries"]["host"])
    assert built.part_map["instances"]["host[0]"] == built.part_map["entries"]["host"]
    assert not built.surfaces and built.attribution is None
    assert {v["code"] for v in built.lints} == {"include_surfaces_dropped"}


def cage_tag(fixtures):
    cage = kernel.build_model(reference("roll-cage-plain"))
    asset = fixtures.add("cage", cage.glb, dimensions=cage.dimensions)
    entry, inspected = fixtures.include(asset, id="cage", name="cage")
    top = next(part["key"] for part in inspected["parts"] if part["name"] == "cage top rail")
    raw = reference("roll-cage-tag.template")
    raw["entries"][0].update(entry)
    raw["entries"][0]["recolor"] = [{"select": top, "material": "tag"}]
    return raw, top


def test_roll_cage_template_recolors_top_rail_and_outbound_print_reads_forward(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    raw, top = cage_tag(fixtures)
    built = fixtures.build(raw)
    checked_result(built)
    output_key = built.includes[0]["partMap"][top]
    rail = next(p for p in built.model.parts if p.key == output_key)
    assert built.model.materials[rail.material]["baseColor"] == pytest.approx(
        module("imports").module("transforms").linear_color("#1f5f3a") + [1])
    panel = next(c for c in built.components if c.role == "print")
    # Source print U increases left-to-right; V increases downward in +Z front view.
    assert np.corrcoef(panel.mesh.positions[:, 0], panel.mesh.uv[:, 0])[0, 1] > .99
    assert np.corrcoef(panel.mesh.positions[:, 1], panel.mesh.uv[:, 1])[0, 1] < -.99
    with Image.open(BytesIO(built.prints["tag"].data)) as image:
        pixels = np.array(image)
        crop = pixels[round(.2*image.height):round(.8*image.height), round(.08*image.width):round(.92*image.width)]
        assert np.count_nonzero(np.all(crop == [255, 255, 255], axis=2)) > 500
    assert built.lints == []


def test_source_to_canonical_then_include_pose_then_group_then_normalization(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    matrix = np.eye(4)
    matrix[:3, :3] = np.diag([.5, 1, .25])
    matrix[:3, 3] = [1, 0, .2]
    asset = fixtures.add("frame", cube_payload(), matrix=matrix.reshape(-1, order="F").tolist())
    entry, _ = fixtures.include(asset, rotateY=90, position=[.3, 0, .5])
    raw = recipe({"id": "group", "group": [entry], "rotate": {"y": 30}, "position": [.2, 0, -.1]})
    built = fixtures.build(raw)
    source = module("imports").module("reader").read_model(cube_payload(), extended_materials=True)
    rotation = module("scene").rotation
    expected = source.parts[0].positions @ matrix[:3, :3].T + matrix[:3, 3]
    expected = expected @ rotation({"y": 90}).T + [.3, 0, .5]
    expected = expected @ rotation({"y": 30}).T + [.2, 0, -.1] + built.shift
    actual = built.components[0].mesh.positions
    assert actual.min(axis=0) == pytest.approx(expected.min(axis=0), abs=1e-6)
    assert actual.max(axis=0) == pytest.approx(expected.max(axis=0), abs=1e-6)
    result = checked_result(built)
    frame = result["includes"][0]["frame"]
    assert frame["yaw"] == pytest.approx(120)
    assert frame["translation"] == pytest.approx(rotation({"y": 30}) @ [.3, 0, .5] + [.2, 0, -.1] + built.shift)


@pytest.mark.parametrize("transform", [
    {"repeat": {"count": 2, "step": [1.2, 0, 0]}}, {"rotate": {"x": 15}}, {"rotate": {"z": 15}},
    {"mirror": {"plane": "x"}}, {"around": {"count": 2, "axis": "y", "center": [0, 0, 0]}}])
def test_patterned_or_tilted_include_builds_but_is_not_anchorable(tmp_path, transform):
    fixtures = CatalogFixture(tmp_path)
    asset = fixtures.add("cube", cube_payload())
    entry, _ = fixtures.include(asset, position=[.6, 0, 0])
    built = fixtures.build(recipe({"id": "assembly", "group": [entry], **transform}))
    checked_result(built)
    assert built.includes[0]["anchorable"] is False and built.includes[0]["frame"] is None
    copies = module("budgets").copies(built.recipe["entries"][0])
    assert built.budgets["triangles"] == 12*copies
    assert built.budgets["primitives"] == copies and built.budgets["includes"] == 1
    assert len(built.part_map["instances"]) == 2*copies


def test_include_scatter_rejects_size_jitter(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    asset = fixtures.add("cube", cube_payload())
    entry, _ = fixtures.include(asset)
    raw = recipe({"id": "assembly", "group": [entry], "scatter": {"count": 1, "seed": 1,
                  "within": {"min": [-2, 0, -2], "max": [2, 4, 2]}, "sizeJitter": [.1, 0, 0]}})
    with pytest.raises(Error) as caught:
        fixtures.build(raw)
    assert caught.value.code == "include_invalid"


def test_duplicate_names_stable_recolor_keys_and_last_matching_rule(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    payload = cube_payload(finish={"appearanceId": "steel"})
    def duplicate(doc):
        doc["nodes"].append({"name": doc["nodes"][0]["name"], "mesh": 0, "translation": [1, 0, 0]})
        doc["scenes"][0]["nodes"].append(1)
    asset = fixtures.add("twins", edit_glb(payload, duplicate))
    entry, inspected = fixtures.include(asset)
    keys = [p["key"] for p in inspected["parts"]]
    assert keys == ["p:housing~0#0", "p:housing~1#0"]
    entry["recolor"] = [{"select": {"all": True}, "material": "paint"}, {"select": keys[1], "material": "red"}]
    built = fixtures.build(recipe(entry, materials={"paint": {"color": "#ffffff"}, "red": {"color": "#ff0000"}}))
    checked_result(built)
    assert len(built.model.parts) == 2  # one node, two material primitives
    assert len(gltf(built.glb)["nodes"]) == 1
    assert all("defaultFinish" not in m for m in built.model.materials)
    assert len(set(built.includes[0]["partMap"].values())) == 2
    assert built.model.materials[1]["baseColor"][:3] == [1, 0, 0]
    entry["recolor"] = [{"select": "p:missing#0", "material": "paint"}]
    with pytest.raises(Error) as caught:
        fixtures.build(recipe(entry))
    assert caught.value.code == "recolor_invalid" and caught.value.path.endswith("recolor[0].select")


def printed_payload():
    raw = recipe(shape("panel", center=[0, .1, 0], size=[.4, .2],
                       print={"background": "#ffffff", "items": [{"text": "OUTBOUND", "box": [.1, .1, .9, .9],
                                                                "color": "#000000"}]}),
                 materials={"paint": {"color": "#333333", "lit": .6}})
    return kernel.build_model(raw)


def test_included_print_keeps_pixels_uv_artwork_emission_and_refuses_recolor(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    original = printed_payload()
    asset = fixtures.add("display", original.glb)
    entry, _ = fixtures.include(asset, rotateY=90)
    built = fixtures.build(recipe(entry))
    checked_result(built)
    material = next(m for m in built.model.materials if m.get("artwork"))
    assert material["baseColor"] == [1, 1, 1, 1]
    assert material["emissive"] == [.6]*3 and material["texture"] == material["emissiveTexture"]
    image = built.model.images[material["texture"]["image"]]
    with Image.open(BytesIO(image.data)) as actual, Image.open(BytesIO(original.prints["body"].data)) as expected:
        assert np.array_equal(np.array(actual), np.array(expected))
    front = next(c for c in built.components if c.include_material and c.include_material.get("artwork"))
    # +90 around Y changes front from +Z to +X: viewer-right is -Z.
    assert np.corrcoef(-front.mesh.positions[:, 2], front.mesh.uv[:, 0])[0, 1] > .99
    entry["recolor"] = [{"select": {"all": True}, "material": "paint"}]
    with pytest.raises(Error) as caught:
        fixtures.build(recipe(entry))
    assert caught.value.code == "recolor_invalid"


def test_included_print_under_group_mirror_keeps_outward_winding_and_readable_uv(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    asset = fixtures.add("display", printed_payload().glb)
    entry, _ = fixtures.include(asset, position=[.3, 0, 0])
    built = fixtures.build(recipe({"id": "mirrored", "group": [entry], "mirror": {"plane": "x"}}))
    checked_result(built)
    fronts = [c for c in built.components if c.include_material and c.include_material.get("artwork")]
    assert len(fronts) == 2
    for front in fronts:
        assert np.corrcoef(front.mesh.positions[:, 0], front.mesh.uv[:, 0])[0, 1] > .99
        face = front.mesh.positions[front.mesh.indices[0]]
        assert np.cross(face[1]-face[0], face[2]-face[0])[2] > 0


def test_textured_non_artwork_recolor_and_artwork_default_finish_are_refused(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    original = printed_payload().glb
    def remove_marker(doc):
        for material in doc["materials"]:
            material["extras"].pop("facilityArtwork", None)
    asset = fixtures.add("texture", edit_glb(original, remove_marker))
    entry, _ = fixtures.include(asset, recolor=[{"select": {"all": True}, "material": "paint"}])
    with pytest.raises(Error) as caught:
        fixtures.build(recipe(entry))
    assert caught.value.code == "recolor_invalid"
    def add_finish(doc):
        next(m for m in doc["materials"] if m["extras"].get("facilityArtwork"))["extras"]["facilityDefaultFinish"] = "steel"
    asset = fixtures.add("invalid-print", edit_glb(original, add_finish))
    entry, _ = fixtures.include(asset)
    with pytest.raises(Error) as caught:
        fixtures.build(recipe(entry), allowed_appearance_ids=["steel"])
    assert caught.value.code == "print_invalid"


def test_include_keeps_emissive_strength_and_distinct_texture_samplers(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    def change(doc):
        front = next(m for m in doc["materials"] if m["extras"].get("facilityArtwork"))
        front["extensions"] = {"KHR_materials_emissive_strength": {"emissiveStrength": 3}}
        doc["extensionsUsed"] = ["KHR_materials_emissive_strength"]
        doc["samplers"].append({"wrapS": 10497, "wrapT": 10497})
        doc["textures"].append({"source": 0, "sampler": 1})
        front["emissiveTexture"] = {"index": 1, "texCoord": 0}
    asset = fixtures.add("emission", edit_glb(printed_payload().glb, change))
    entry, _ = fixtures.include(asset)
    built = fixtures.build(recipe(entry))
    checked_result(built)
    doc = gltf(built.glb)
    assert len(doc["images"]) == 1 and len(doc["textures"]) == 2
    front = next(m for m in built.model.materials if m.get("artwork"))
    assert front["emissive"] == pytest.approx([1.8]*3)
    assert front["texture"]["wrapS"] == 33071 and front["emissiveTexture"]["wrapS"] == 10497


def test_two_finish_groups_are_namespaced_and_default_adjustments_survive(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    payload = cube_payload(finish={"appearanceId": "steel", "roughness": .2, "color": "#aabbcc"})
    payload = edit_glb(payload, lambda d: d["materials"][0]["extras"].update(facilityFinishGroup="lamps"))
    asset = fixtures.add("lamp", payload)
    left, _ = fixtures.include(asset, id="left", name="left")
    right, _ = fixtures.include(asset, id="right", name="right", position=[1.2, 0, 0])
    built = fixtures.build(recipe(left, right), allowed_appearance_ids=["steel"])
    checked_result(built, ["steel"])
    assert {m["finishGroup"] for m in built.model.materials} == {"left:lamps", "right:lamps"}
    assert all(m["defaultFinish"] == {"appearanceId": "steel", "roughness": .2, "color": "#aabbcc"}
               for m in built.model.materials)
    # Carry the namespaces through a second composition level.
    nested_asset = fixtures.add("nested", built.glb)
    nested, _ = fixtures.include(nested_asset, id="outer")
    result = fixtures.build(recipe(nested), allowed_appearance_ids=["steel"])
    checked_result(result, ["steel"])
    assert {m["finishGroup"] for m in result.model.materials} == {"outer:left:lamps", "outer:right:lamps"}


def test_cc_by_credit_survives_nested_include_and_second_credit_refuses(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    asset = fixtures.add("credited", cube_payload(), source={}, attribution=credit())
    entry, _ = fixtures.include(asset)
    first = fixtures.build(recipe(entry))
    assert first.attribution == credit()
    nested_asset = fixtures.add("nested", first.glb, attribution=first.attribution)
    nested, _ = fixtures.include(nested_asset, id="nested")
    second = fixtures.build(recipe(nested))
    assert checked_result(second)["attribution"] == credit()
    with pytest.raises(Error) as caught:
        fixtures.build(recipe(entry, nested))
    assert caught.value.code == "include_licence"


def test_budget_refuses_before_reader_decodes_arrays(tmp_path, monkeypatch):
    from tests.model_builder_composition_support import triangle_glb
    fixtures = CatalogFixture(tmp_path)
    asset = fixtures.add("heavy", triangle_glb(triangles=60001))
    entry, _ = fixtures.include(asset)
    monkeypatch.setattr(module("imports").module("reader"), "read_model", lambda *a, **k: pytest.fail("decoded over-budget include"))
    with pytest.raises(Error) as caught:
        fixtures.build(recipe(entry))
    assert caught.value.code == "budget_exceeded" and caught.value.triangles == 60001
