"""MI0b recipe, transform, footprint and deterministic writer contracts."""
from copy import deepcopy
from io import BytesIO
import json
import math
import struct

import jsonschema
import numpy as np
from PIL import Image
import pytest

from tests.model_import_test_support import Fixture, image_bytes, module, textured_box
from tests.model_import_recipe_support import add_spec, prepare_fixture, recipe, six_recipes, solids

recipes = module("recipe")
transforms = module("transforms")
ModelImportError = module("errors").ModelImportError


def gltf(payload):
    return json.loads(payload[20:20 + struct.unpack_from("<I", payload, 12)[0]])


def test_schema_is_draft_2020_12_and_defaults_are_canonical():
    jsonschema.Draft202012Validator.check_schema(recipes.RECIPE_SCHEMA)
    raw = recipe(name="  Bowl  set ", rotate={"y": 90.0000001}, size={"scale": 1.23456789},
                 parts=[{"select": {"all": True}, "material": {"color": "#AAbBcc"}}])
    normalized = recipes.normalize_recipe(raw)
    jsonschema.Draft202012Validator(recipes.RECIPE_SCHEMA).validate(normalized)
    assert normalized["name"] == "Bowl set"
    assert normalized["rotate"] == {"x": 0, "y": 90, "z": 0}
    assert normalized["size"] == {"scale": 1.234568}
    assert normalized["parts"][0]["material"]["color"] == "#aabbcc"
    assert normalized["copies"] == [{"x": 0, "z": 0, "turnDegrees": 0, "scale": 1}]
    assert recipes.normalize_recipe(normalized) == normalized
    assert normalized["parts"][0]["material"]["texture"] == "keep"
    assert raw["name"] == "  Bowl  set "


INVALID_FIELDS = [
    {"name": "x" * 81}, {"name": "  "}, {"category": ""}, {"description": "x" * 301},
    {"tags": ["a"] * 9}, {"tags": ["x" * 81]}, {"rotate": {"y": 361}}, {"rotate": {"q": 1}},
    {"size": {"scale": .00001}}, {"size": {"scale": True}}, {"size": {"meters": .001, "dimension": "width"}},
    {"size": {"meters": 31, "dimension": "height"}}, {"size": {"meters": 1, "dimension": "radius"}},
    {"size": {"scale": 1, "meters": 1, "dimension": "width"}}, {"parts": [{"select": {"all": True}}] * 65},
    {"parts": [{"select": {"all": False}}]}, {"parts": [{"select": {"part": "p0", "all": True}}]},
    {"parts": [{"select": {"all": True}, "move": [0, 0, 0], "moveTo": [0, 0, 0]}]},
    {"parts": [{"select": {"all": True}, "move": [0, 0]}]},
    {"parts": [{"select": {"all": True}, "move": [101, 0, 0]}]},
    {"parts": [{"select": {"all": True}, "scale": 21}]},
    {"parts": [{"select": {"all": True}, "material": {"texture": "replace"}}]},
    {"parts": [{"select": {"all": True}, "material": {"color": "red"}}]},
    {"parts": [{"select": {"all": True}, "material": {"roughness": 1.1}}]},
    {"parts": [{"select": {"all": True}, "material": {"metalness": -.1}}]},
    {"parts": [{"select": {"all": True}, "material": {"alphaCutoff": .99}}]},
    {"parts": [{"select": {"all": True}, "material": {"doubleSided": 1}}]},
    {"textureMaxPx": 128}, {"textureMaxPx": True}, {"copies": []}, {"copies": [{}] * 13},
    {"copies": [{"scale": .4}]}, {"add": [add_spec()] * 9}, {"add": [add_spec(hollow=.1)]},
    {"add": [add_spec("cylinder", hollow=.2)]}, {"add": [add_spec("cylinder", height=0)]},
    {"surfaces": [{"id": "a", "label": "a", "height": 1, "rect": [1, 0, 0, 1]}]},
    {"surfaces": [{"id": "a", "label": "a", "height": 1, "rect": [0, 0, 1, 1]}] * 2},
    {"footprint": "base"}, {"changesNote": "x" * 201}, {"attribution": {"author": "me"}},
    {"attribution": {"statedBy": "user", "sourceUrl": "http://example.test"}},
    {"unknown": 1}, {"importId": "../other"}, {"pivot": {"parts": []}},
    {"rotate": {"x": float("nan")}}, {"size": {"scale": float("inf")}},
]


@pytest.mark.parametrize("fields", INVALID_FIELDS)
def test_recipe_rejects_invalid_fields(fields):
    with pytest.raises(ModelImportError) as caught:
        recipes.normalize_recipe(recipe(**fields))
    assert caught.value.code == "recipe_invalid"


@pytest.mark.parametrize("fields", INVALID_FIELDS)
def test_schema_and_normalizer_both_enforce_structural_caps(fields):
    # Whitespace, URLs, hollow proportions, rectangle order/duplicate ids, and
    # non-finite numbers require semantic checks after JSON Schema validation.
    value = recipe(**fields)
    errors = list(jsonschema.Draft202012Validator(recipes.RECIPE_SCHEMA).iter_errors(value))
    if not errors:
        with pytest.raises(ModelImportError):
            recipes.normalize_recipe(value)


def test_every_recipe_field_is_retained_and_normalized():
    raw = recipe(description=" A  useful object ", tags=[" counter  decor "],
                 rotate={"x": 1, "y": 2, "z": 3}, pivot={"parts": [{"mesh": "mesh"}]},
                 size={"dimension": "largest", "meters": 2}, textureMaxPx=256,
                 parts=[{"select": {"part": "p0"}, "name": " front ", "drop": False, "scale": 2,
                         "turnDegrees": 45, "moveTo": [1, 2, 3],
                         "material": {"color": "#FFEEDD", "roughness": .2, "metalness": .4, "texture": "keep",
                                      "emissive": "keep", "alpha": "blend", "alphaCutoff": .3, "doubleSided": True}}],
                 copies=[{"x": 2, "z": 3, "turnDegrees": -30, "scale": .5}],
                 add=[add_spec("box"), add_spec("cylinder", "round"), add_spec("frustum", "pot", hollow=.01)],
                 surfaces=[{"id": "top", "label": " Top ", "height": .5, "rect": [-.2, -.3, .4, .5]}],
                 footprint="box", attribution={"statedBy": "user", "title": " Source ", "author": "Person",
                    "authorUrl": "https://example.test/person", "sourceUrl": "https://example.test/model",
                    "license": "CC BY 4.0", "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
                    "licenseClass": "cc-by"}, changesNote=" User requested ")
    normalized = recipes.normalize_recipe(raw)
    assert set(normalized) == set(recipes.RECIPE_SCHEMA["properties"])
    assert normalized["description"] == "A useful object"
    assert normalized["tags"] == ["counter decor"] and normalized["changesNote"] == "User requested"
    assert normalized["parts"][0]["name"] == "front"
    assert normalized["attribution"]["title"] == "Source"
    assert recipes.normalize_recipe(normalized) == normalized


@pytest.mark.parametrize("selector", [{"part": "p0"}, {"mesh": "mesh"}, {"node": "node"},
                                      {"material": "paint"}, {"all": True}])
def test_each_selector(selector):
    source = module("reader").read_model(textured_box().bytes())
    assert [p.key for p in transforms.select_parts(source.parts, source.materials, selector)] == ["p0"]


@pytest.mark.parametrize("selector,closest", [({"part": "p7"}, "p0"), ({"mesh": "mes"}, "mesh"),
                                             ({"node": "nod"}, "node"), ({"material": "pait"}, "paint")])
def test_selector_failure_names_closest_source_values(selector, closest):
    source = module("reader").read_model(textured_box().bytes())
    with pytest.raises(ModelImportError) as caught:
        transforms.select_parts(source.parts, source.materials, selector)
    assert caught.value.code == "recipe_selector_empty"
    assert closest in caught.value.details["closest"]


@pytest.mark.parametrize("dimension,axis", [("width", 0), ("height", 1), ("depth", 2), ("largest", None)])
def test_size_dimension_after_rotation(dimension, axis):
    fixture = solids([add_spec(size=[2, 3, 4])])
    draft, _, _ = prepare_fixture(fixture, recipe(rotate={"x": 90}, size={"dimension": dimension, "meters": 2}))
    size = [draft["dimensions"][k] for k in ("width", "height", "depth")]
    assert (max(size) if axis is None else size[axis]) == pytest.approx(2, abs=1e-6)


def test_d11_order_about_own_base_then_copy_then_add_then_normalize():
    fixture = solids([add_spec(size=[2, 1, 4])])
    raw = recipe(rotate={"y": 90}, size={"dimension": "width", "meters": 2},
                 parts=[{"select": {"all": True}, "name": "turned", "scale": 2,
                         "turnDegrees": 90, "moveTo": [1, 2, 3]}],
                 copies=[{"x": 4, "z": 5, "turnDegrees": 90, "scale": .5}],
                 add=[add_spec(size=[1, 1, 1], position=[0, 0, 0], name="added")])
    draft, _, model = prepare_fixture(fixture, raw)
    # Source -> [4,1,2] -> [2,.5,1] -> [2,1,4], base [1,2,3].
    # Copy about origin -> [2,.5,1], base [5.5,1,4.5]; add stays at origin.
    assert draft["dimensions"] == pytest.approx({"width": 7, "height": 1.5, "depth": 5.5})
    np.testing.assert_allclose(transforms.base_center(model.parts[0]) - transforms.base_center(model.parts[1]),
                               [5.5, 1, 4.5], atol=1e-6)
    assert model.parts[0].name == "turned"


def test_xyz_global_rotation_order_and_normals():
    source = module("reader").read_model(textured_box().bytes())
    normalized = recipes.normalize_recipe(recipe(rotate={"x": 30, "y": 40, "z": 50}))
    result = transforms.transform_model(source, normalized)
    matrix = transforms.rotation(30, 40, 50)
    expected = (source.parts[0].positions - [.5, 0, .5]) @ matrix.T
    low, high = expected.min(axis=0), expected.max(axis=0)
    expected -= [(low[0] + high[0]) / 2, low[1], (low[2] + high[2]) / 2]
    np.testing.assert_allclose(result.parts[0].positions, expected, atol=2e-7)
    np.testing.assert_allclose(result.parts[0].normals, source.parts[0].normals @ matrix.T, atol=2e-7)


def test_rule_order_drop_and_source_material_identity():
    fixture = solids([add_spec(name="first"), add_spec(name="second", position=[2, 0, 0])])
    draft, _, model = prepare_fixture(fixture, recipe(parts=[
        {"select": {"material": "first"}, "name": "renamed", "move": [1, 2, 3]},
        {"select": {"material": "first"}, "move": [2, 1, -1], "material": {"texture": "drop"}},
        {"select": {"material": "second"}, "drop": True}]))
    assert draft["partsTotal"] == 1 and model.parts[0].name == "renamed"
    assert draft["dimensions"] == pytest.approx({"width": 1, "height": 1, "depth": 1})
    with pytest.raises(ModelImportError, match="matched nothing"):
        prepare_fixture(fixture, recipe(parts=[{"select": {"all": True}, "drop": True},
                                               {"select": {"part": "p0"}, "name": "gone"}]))


@pytest.mark.parametrize("shape", ["box", "cylinder", "frustum"])
@pytest.mark.parametrize("hollow", [False, True])
def test_added_shapes_faces_bounds_and_open_floor(shape, hollow):
    if hollow and shape == "box":
        return
    spec = add_spec(shape, hollow=.01) if hollow else add_spec(shape)
    part, material = module("simple_parts").added_part(spec, 0)
    assert part.positions[:, 1].min() == 0
    height = spec["size"][1] if shape == "box" else spec["height"]
    assert part.positions[:, 1].max() == height
    assert np.all(np.isfinite(part.normals))
    faces = part.positions[part.indices]
    cross = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    assert np.all(np.einsum("ij,ij->i", cross, part.normals[part.indices[:, 0]]) > 0)
    assert material["texture"] is None and material["metalness"] == 0
    if hollow:
        # No top disk; the upward top is only a rim. The inside floor is at wall thickness.
        centers = faces.mean(axis=1)
        top = np.isclose(centers[:, 1], height)
        inner_radius = spec.get("radius", spec.get("radiusTop")) - spec["hollow"]
        assert np.all(np.linalg.norm(centers[top][:, [0, 2]], axis=1) > inner_radius * .98)
        assert np.any(np.isclose(centers[:, 1], spec["hollow"]))
        # Internal wall faces point inward, external wall faces outward.
        radial_dot = (part.positions[:, [0, 2]] * part.normals[:, [0, 2]]).sum(axis=1)
        assert np.any(radial_dot < 0) and np.any(radial_dot > 0)


def test_textures_redecoded_after_alpha_patch_and_resized_with_metadata_stripped():
    fixture = textured_box()
    primitive = fixture.document["meshes"][0]["primitives"][0]
    fixture.document["images"] = []
    fixture.document["textures"] = []
    texture = fixture.image(image_bytes(size=(1200, 600)))
    fixture.document["materials"][0]["alphaMode"] = "OPAQUE"
    fixture.document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]["index"] = texture
    fixture.document["materials"][0]["emissiveFactor"] = [.2, .1, .3]
    for mode, expected_mime in (("mask", "image/png"), ("opaque", "image/jpeg"), ("blend", "image/png")):
        draft, output, model = prepare_fixture(fixture, recipe(textureMaxPx=256, parts=[
            {"select": {"all": True}, "material": {"color": "#808080", "alpha": mode, "alphaCutoff": .25,
                                                  "doubleSided": False, "roughness": .2, "metalness": .7,
                                                  "emissive": "off"}}]))
        image = model.images[0]
        assert (image.width, image.height) == (256, 128) and image.mime_type == expected_mime
        with Image.open(BytesIO(image.data)) as decoded:
            assert not decoded.getexif() and "icc_profile" not in decoded.info
            if mode != "opaque":
                assert decoded.getextrema()[3] == (128, 128)
        document = gltf(output)
        material = document["materials"][0]
        assert material["alphaMode"] == mode.upper() and material["alphaCutoff"] == .25
        assert material["emissiveFactor"] == [0, 0, 0] and material["doubleSided"] is False
        assert material["pbrMetallicRoughness"]["baseColorFactor"][:3] == pytest.approx([.2158605] * 3)
        assert material["pbrMetallicRoughness"]["roughnessFactor"] == .2
        assert material["pbrMetallicRoughness"]["metallicFactor"] == .7
        assert document["images"][0]["mimeType"] == expected_mime
        assert draft["materials"][0]["textureSize"] == [256, 128]
    _, _, restored = prepare_fixture(fixture, recipe(textureMaxPx=2048))
    assert restored.images[0].width == 1200  # MI0a cache was limited to 1024
    _, output, _ = prepare_fixture(fixture, recipe(parts=[
        {"select": {"all": True}, "material": {"texture": "drop", "emissive": "keep"}}]))
    assert "images" not in gltf(output)
    assert gltf(output)["materials"][0]["emissiveFactor"] == pytest.approx([.2, .1, .3])


def test_unlit_emissive_strength_and_baked_uv_are_written_once():
    fixture = textured_box()
    fixture.document["extensionsUsed"] = ["KHR_materials_unlit", "KHR_materials_emissive_strength", "KHR_texture_transform"]
    material = fixture.document["materials"][0]
    material["extensions"] = {"KHR_materials_unlit": {}, "KHR_materials_emissive_strength": {"emissiveStrength": 4}}
    material["emissiveFactor"] = [.5, 1, .25]
    material["pbrMetallicRoughness"]["baseColorTexture"]["extensions"] = {
        "KHR_texture_transform": {"offset": [.2, .3], "scale": [2, 3]}}
    _, output, model = prepare_fixture(fixture)
    result = gltf(output)
    assert result["extensionsUsed"] == ["KHR_materials_emissive_strength", "KHR_materials_unlit"]
    assert result["materials"][0]["extensions"]["KHR_materials_emissive_strength"]["emissiveStrength"] == 4
    reread = module("reader").read_model(output)
    np.testing.assert_allclose(reread.parts[0].uv0, model.parts[0].uv0)
    assert result["materials"][0]["extras"]["facilityMaterialRole"] == model.parts[0].name


@pytest.mark.parametrize("case", ["table", "canopy", "elevated"])
def test_footprint_contains_whole_model_not_only_base(case):
    small = add_spec(size=[.2, .5, .2], name="base")
    large = add_spec(size=[2, .1, 1], position=[.2, .5, 0], name=case)
    _, _, model = prepare_fixture(solids([large] if case == "elevated" else [small, large]))
    polygon = module("footprint").footprint(model.parts)[0]
    assert min(p["x"] for p in polygon) == pytest.approx(-1)
    assert max(p["x"] for p in polygon) == pytest.approx(1)
    assert max(p["z"] for p in polygon) - min(p["z"] for p in polygon) == pytest.approx(1)


def test_outward_hull_simplification_contains_all_points_and_stays_in_bounds():
    fixture = solids([add_spec("cylinder", radius=1, height=1)])
    source = module("reader").read_model(fixture.bytes())
    part = source.parts[0]
    angles = np.arange(97) * math.tau / 97
    part.positions = np.array([[math.cos(a), y, math.sin(a)] for y in (0, 1) for a in angles], dtype=np.float32)
    low, high = transforms.bounds([part])
    center = (low + high) / 2
    part.positions[:, [0, 2]] -= center[[0, 2]]
    hull = module("footprint").footprint([part])[0]
    assert 3 <= len(hull) <= 32
    points = np.array([[p["x"], p["z"]] for p in hull])
    for a, b in zip(points, np.roll(points, -1, axis=0)):
        relative = part.positions[:, [0, 2]] - a
        assert np.min((b[0] - a[0]) * relative[:, 1] - (b[1] - a[1]) * relative[:, 0]) >= -1e-9
    assert np.all(points.min(axis=0) >= part.positions[:, [0, 2]].min(axis=0) - 1e-9)
    assert np.all(points.max(axis=0) <= part.positions[:, [0, 2]].max(axis=0) + 1e-9)


@pytest.mark.parametrize("case", range(6))
def test_six_reference_recipes_on_synthetic_lookalikes(case):
    name, fixture, raw = six_recipes()[case]
    assert len(module("validation").json_bytes(raw)) < 8192
    draft, payload, model = prepare_fixture(fixture, raw)
    from ai_inspector.industrial_assets.primitives import verify
    from ai_inspector.industrial_assets.artifacts import inspect_glb
    assert verify(payload, draft["dimensions"])["triangles"] == draft["triangles"]
    assert inspect_glb(payload).scene_triangle_count == draft["triangles"]
    if name == "bowl":
        assert .3 <= draft["dimensions"]["width"] <= .4
    elif name == "board":
        assert draft["dimensions"]["width"] == pytest.approx(.41, abs=1e-6)
        assert draft["dimensions"]["height"] == pytest.approx(.32, abs=1e-6)
    elif name == "mugs":
        assert draft["dimensions"]["height"] == pytest.approx(.095, abs=1e-7)
        spans = sorted((p.positions[:, 2].min(), p.positions[:, 2].max()) for p in model.parts)
        assert all(left[1] < right[0] for left, right in zip(spans, spans[1:]))
    elif name == "olive":
        assert draft["dimensions"]["height"] == pytest.approx(1.35, abs=.03)
        trunk = next(p for p in model.parts if p.name == "olive trunk")
        pot = next(p for p in model.parts if p.name == "terracotta pot")
        assert np.linalg.norm((transforms.base_center(trunk) - transforms.base_center(pot))[[0, 2]]) < .02
    elif name == "basil":
        assert draft["dimensions"]["height"] == pytest.approx(.3, abs=1e-6)
        assert .35 < draft["dimensions"]["depth"] < .4
    else:
        assert draft["dimensions"] == pytest.approx({"width": .82, "height": .55, "depth": .1}, abs=1e-6)
        assert sorted(round(transforms.base_center(p)[1], 2) for p in model.parts) == [0, 0, 0, .35, .35]


def test_output_byte_limit_and_triangle_diagnostics(monkeypatch):
    fixture = textured_box()
    source = module("reader").read_model(fixture.bytes())
    source.parts[0].indices = np.tile(source.parts[0].indices, (21000, 1))
    with pytest.raises(ModelImportError) as caught:
        transforms.transform_model(source, recipes.normalize_recipe(recipe()))
    assert caught.value.code == "model_output_too_complex"
    assert caught.value.details["triangles"] == 252000
    assert caught.value.details["largestParts"][0]["name"] == "paint"
    monkeypatch.setattr(module("writer"), "GLB_BYTES", 100)
    with pytest.raises(ModelImportError) as caught:
        prepare_fixture(fixture)
    assert caught.value.code == "model_output_too_large"


def test_identity_determinism_and_each_identity_input():
    fixture = textured_box()
    draft, first, _ = prepare_fixture(fixture)
    repeated, second, _ = prepare_fixture(fixture)
    assert first == second and repeated == draft
    identity = module("identity")
    original = identity.asset_identity(draft)
    assert original == identity.asset_identity(deepcopy(draft))
    for key, value in (("engineVersion", "other"), ("sourceSha256", "a" * 64), ("outputSha256", "b" * 64)):
        changed = {**draft, key: value}
        assert identity.asset_identity(changed)["assetId"] != original["assetId"]
    changed = deepcopy(draft)
    changed["recipe"]["changesNote"] = "A deliberate recipe change"
    assert identity.asset_identity(changed)["assetId"] != original["assetId"]
    entry = identity.catalog_semantics(draft)
    for key in identity.SEMANTIC_FIELDS:
        changed_entry = deepcopy(entry)
        changed_entry[key] = {"changed": key}  # Pure identity hashes every semantic field.
        assert identity.asset_identity(draft, changed_entry)["assetId"] != original["assetId"]
    assert identity.asset_identity(draft, {**entry, "artifact": "elsewhere.glb", "assetId": "ignored"}) == original


def test_credit_changes_note_and_conflicting_source_evidence():
    fixture = textured_box()
    fixture.document["asset"]["extras"] = {"license": "CC BY 4.0",
        "licenseUrl": "https://creativecommons.org/licenses/by-nc-nd/4.0/", "author": "Original author"}
    draft, _, _ = prepare_fixture(fixture, recipe(changesNote="User requested plain finish", parts=[
        {"select": {"all": True}, "material": {"texture": "drop"}}]))
    assert draft["attribution"]["licenseClass"] == "unknown"
    assert draft["attribution"]["author"] == "Original author" and draft["attribution"]["statedBy"] == "file"
    assert "plain material instead of texture" in draft["changes"]
    assert draft["changes"].endswith("User requested plain finish") and len(draft["changes"]) <= 600
    assert draft["warnings"]
    credits = module("credit").credits_text(draft["attribution"])
    assert "Author: Original author\n" in credits and "Changes: " in credits
    corrected, _, _ = prepare_fixture(fixture, recipe(attribution={"statedBy": "user", "license": "CC0",
                                                                   "licenseUrl": "", "licenseClass": "cc0"}))
    assert corrected["attribution"]["licenseClass"] == "cc0"


def test_support_surfaces_and_footprint_bind_with_real_catalog(tmp_path):
    from ai_inspector.facility_layout.host import PRIVATE_ASSET_MANIFEST, _private_manifest_specs
    from ai_inspector.industrial_assets.primitives import verify
    raw = recipe(surfaces=[{"id": "top", "label": "Top", "height": 1, "rect": [-.4, -.3, .2, .4]}],
                 footprint="box")
    draft, payload, _ = prepare_fixture(textured_box(), raw)
    surface = draft["surfaces"][0]
    assert surface["localFrame"]["origin"] == pytest.approx({"x": -.1, "y": 1, "z": .05})
    assert surface["bounds"] == pytest.approx({"minimumX": -.3, "maximumX": .3,
                                              "minimumZ": -.35, "maximumZ": .35})
    identity = module("identity").asset_identity(draft)
    entry = module("identity").catalog_semantics(draft)
    entry.pop("attribution")  # Catalog credit projection arrives in MI2.
    entry.update(assetId=identity["assetId"], artifact="model.glb",
                 sourceToCanonical=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    manifest = tmp_path / PRIVATE_ASSET_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_bytes(module("validation").json_bytes({"schemaVersion": 1, "assets": [entry]}))
    bound = _private_manifest_specs(tmp_path)[0]
    assert bound["support_surfaces"][0] == surface
    assert bound["footprint_polygons"] == draft["footprint"]
    assert verify(payload, draft["dimensions"])["triangles"] == 12


def test_identity_changes_for_every_recipe_field_even_when_output_bytes_match():
    fixture = textured_box()
    draft, payload, _ = prepare_fixture(fixture)
    identity = module("identity")
    original = identity.asset_identity(draft)
    for key in draft["recipe"]:
        changed = deepcopy(draft)
        changed["recipe"][key] = "Different name" if key == "name" else {"changed": key}
        assert identity.asset_identity(changed)["assetId"] != original["assetId"]
    metadata_only, second, _ = prepare_fixture(fixture, recipe(description="Different catalog description"))
    assert payload == second
    assert identity.asset_identity(metadata_only)["assetId"] != original["assetId"]


def test_explicit_defaults_normalize_to_same_recipe():
    minimal = recipe(parts=[{"select": {"all": True}}])
    explicit = recipe(parts=[{"select": {"all": True}, "drop": False, "scale": 1, "turnDegrees": 0,
                              "move": [0, 0, 0], "material": {"texture": "keep", "emissive": "keep"}}],
                      rotate={"x": 0, "y": 0, "z": 0}, size={"scale": 1}, pivot="base",
                      copies=[{"x": 0, "z": 0, "turnDegrees": 0, "scale": 1}], textureMaxPx=1024,
                      add=[], surfaces=[], tags=[], changesNote="", footprint="hull")
    assert recipes.normalize_recipe(minimal) == recipes.normalize_recipe(explicit)


def test_shared_material_with_mixed_uv_presence_keeps_the_textured_part():
    fixture = textured_box()
    textured = fixture.document["meshes"][0]["primitives"][0]
    plain = deepcopy(textured)
    plain["attributes"].pop("TEXCOORD_0")
    fixture.document["meshes"][0]["primitives"] = [plain, textured]
    draft, payload, model = prepare_fixture(fixture)
    document = gltf(payload)
    material0 = document["materials"][document["meshes"][0]["primitives"][0]["material"]]
    material1 = document["materials"][document["meshes"][1]["primitives"][0]["material"]]
    assert "baseColorTexture" not in material0["pbrMetallicRoughness"]
    assert "baseColorTexture" in material1["pbrMetallicRoughness"]
    assert draft["materialsTotal"] == 2
    assert model.materials[model.parts[0].material]["texture"] is None
    assert model.materials[model.parts[1].material]["texture"] is not None
