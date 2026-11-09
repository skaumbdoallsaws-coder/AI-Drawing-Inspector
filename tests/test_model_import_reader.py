"""MI0a acceptance: generated good/hostile containers, arrays, graphs and images."""
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import json
import math
import struct
import zipfile

import numpy as np
from PIL import Image
import pytest

from tests.model_import_test_support import Fixture, glb, image_bytes, module, textured_box, unzip_model, zip_bytes

reader = module("reader")
containers = module("containers")
limits = module("limits")
materials = module("materials")
licence = module("licence")
summary_module = module("summary")
protocol = module("protocol")
ModelImportError = module("errors").ModelImportError


def refused(payload, code="gltf_invalid", **options):
    with pytest.raises(ModelImportError) as caught:
        reader.read_model(payload, **options)
    assert caught.value.code == code
    assert len(str(caught.value)) <= 180


def test_textured_box_summary_and_paging():
    model = reader.read_model(textured_box().bytes(), "../box.glb")
    assert model.name == "box.glb"
    assert model.parts[0].key == "p0" and model.parts[0].name == "paint"
    assert model.parts[0].positions.dtype == np.float32
    assert model.parts[0].indices.dtype == np.uint32
    assert len(model.parts[0].indices) == 12
    assert model.images[0].mime_type == "image/png"
    summary = summary_module.build_summary(model)
    protocol.validate_summary(summary)
    assert summary["rawSize"] == {"width": 1, "height": 1, "depth": 1}
    assert summary["triangles"] == 12 and summary["nextPartsOffset"] is None
    assert summary["flatTopHints"] and not summary["flatTopHints"][0]["verifiedSupport"]
    assert len(module("validation").json_bytes(summary)) <= 48 * 1024


def test_zip_relative_resources_and_sketchfab_credit():
    fixture = Fixture()
    primitive = fixture.triangle()
    primitive["attributes"]["TEXCOORD_0"] = fixture.array([[0, 0], [1, 0], [0, 1]], "VEC2")
    fixture.document["images"] = [{"uri": "../textures/leaf%20one.png", "mimeType": "wrong/type"}]
    fixture.document["textures"] = [{"source": 0}]
    fixture.document["materials"] = [{"name": "leaves", "alphaMode": "MASK",
                                      "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]
    primitive["material"] = 0
    text = ('Model Information:\n* title: Test tree\n* source: https://sketchfab.com/3d-models/test\n'
            '* author: Test author (https://sketchfab.com/test)\n'
            'Model License:\n* license type: CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/)\n')
    payload = unzip_model(fixture.document, bytes(fixture.blob), text=text,
                          resources={"textures/leaf one.png": image_bytes()})
    model = reader.read_model(payload)
    assert model.format == "gltf-zip" and model.licence["class"] == "cc-by"
    assert model.licence["title"] == "Test tree" and model.licence["author"] == "Test author"
    assert model.licence["authorUrl"] == "https://sketchfab.com/test"
    assert len(model.images) == 1 and not model.licence["conflicts"]


def test_wrapped_glb_and_no_extraction():
    fixture = Fixture()
    fixture.triangle()
    content = containers.open_container(zip_bytes({"pack/model.glb": fixture.bytes(), "LICENSE.txt": b"CC BY"}))
    assert content.format == "glb-zip" and content.binary
    assert set(content.entries) == {"pack/model.glb", "LICENSE.txt"}


@pytest.mark.parametrize("name", ["../model.glb", "/model.glb", "C:/model.glb", "a/../../model.glb",
                                 r"..\model.glb", r"\\host\share\model.glb", "a/\0/model.glb"])
def test_zip_unsafe_paths(name):
    refused(zip_bytes({name: b"glTF"}), "zip_unsafe")


def test_zip_case_duplicate_and_file_directory_alias():
    refused(zip_bytes({"model.glb": b"x", "MODEL.GLB": b"y"}), "zip_unsafe")
    refused(zip_bytes({"a.bin": b"x", "a.bin/model.glb": b"y"}), "zip_unsafe")


def test_zip_symlink():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("model.glb")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        archive.writestr(info, b"outside")
    refused(buffer.getvalue(), "zip_unsafe")


def test_zip_encrypted_flag_and_unsupported_method():
    payload = bytearray(zip_bytes({"model.glb": b"x"}))
    central = payload.index(b"PK\x01\x02")
    struct.pack_into("<H", payload, 6, 1)
    struct.pack_into("<H", payload, central + 8, 1)
    refused(bytes(payload), "zip_unsafe")
    refused(zip_bytes({"model.glb": b"x"}, compression=zipfile.ZIP_BZIP2), "zip_unsafe")


@pytest.mark.parametrize("change", [{"zip_entries": 1}, {"zip_bytes": 3}, {"text_bytes": 3}, {"text_files": 0}])
def test_zip_declared_budgets(change):
    payload = zip_bytes({"model.glb": b"glTF", "license.txt": b"credit"})
    refused(payload, "zip_too_large", limits=replace(limits.DEFAULT_LIMITS, **change))


def test_zip_ratio_and_corruption():
    refused(zip_bytes({"model.glb": b"0" * 100000}, compression=zipfile.ZIP_DEFLATED), "zip_too_large")
    damaged = bytearray(zip_bytes({"model.glb": b"glTFbroken"}))
    damaged[damaged.index(b"glTFbroken")] ^= 1
    refused(bytes(damaged), "zip_unsafe")


def test_actual_decompressed_size_is_capped(monkeypatch):
    class Overlong(BytesIO):
        def __init__(self):
            super().__init__(b"x" * 8)
    payload = zip_bytes({"model.glb": b"x"})
    monkeypatch.setattr(zipfile.ZipFile, "open", lambda *a, **k: Overlong())
    refused(payload, "zip_too_large")


@pytest.mark.parametrize("entries", [{"a.glb": b"a", "b.gltf": b"b"}, {"mesh.obj": b"v 0 0 0"},
                                    {"license.txt": b"only credit"}])
def test_exactly_one_model(entries):
    refused(zip_bytes(entries), "model_format_unsupported")


@pytest.mark.parametrize("uri", ["https://example.invalid/file.bin", "data:application/octet-stream;base64,AA==",
                                "//host/share", "C:/data.bin", r"..\..\escape.bin", "%2e%2e/%2e%2e/out.bin",
                                "scene.bin?download=1", "scene.bin#fragment", "%ZZ", "bad%00name"])
def test_resource_uris(uri):
    fixture = Fixture()
    fixture.triangle()
    fixture.document["buffers"][0]["uri"] = uri
    payload = zip_bytes({"pack/model.gltf": json.dumps(fixture.document).encode()})
    refused(payload, "gltf_external_resource")


def test_backslash_and_percent_encoded_relative_resource():
    fixture = Fixture()
    fixture.triangle()
    fixture.document["buffers"][0]["uri"] = r"data\scene%20one.bin"
    payload = zip_bytes({"pack/model.gltf": json.dumps(fixture.document).encode(),
                         "pack/data/scene one.bin": bytes(fixture.blob)})
    assert reader.read_model(payload).parts[0].key == "p0"


def test_glb_external_resource_refused_even_inside_zip():
    fixture = Fixture()
    fixture.triangle()
    fixture.document["buffers"][0]["uri"] = "scene.bin"
    refused(fixture.bytes(), "gltf_external_resource")
    refused(zip_bytes({"model.glb": fixture.bytes(), "scene.bin": bytes(fixture.blob)}), "gltf_external_resource")


@pytest.mark.parametrize("kind", ["truncate", "header_length", "version", "chunk_length", "chunk_type", "extra_json"])
def test_glb_structure(kind):
    fixture = Fixture()
    fixture.triangle()
    data = bytearray(fixture.bytes())
    if kind == "truncate":
        data = data[:-1]
    elif kind == "header_length":
        struct.pack_into("<I", data, 8, len(data) + 4)
    elif kind == "version":
        struct.pack_into("<I", data, 4, 1)
    elif kind == "chunk_length":
        struct.pack_into("<I", data, 12, len(data))
    elif kind == "chunk_type":
        struct.pack_into("<I", data, 16, 0)
    else:
        data += struct.pack("<II", 4, 0x4E4F534A) + b"{}  "
        struct.pack_into("<I", data, 8, len(data))
    refused(bytes(data))


def test_format_upload_and_json_limits():
    refused(b"not glb", "model_format_unsupported")
    fixture = Fixture()
    fixture.triangle()
    refused(fixture.bytes(), "model_too_large", limits=replace(limits.DEFAULT_LIMITS, upload_bytes=20))
    refused(fixture.bytes(), "gltf_too_complex", limits=replace(limits.DEFAULT_LIMITS, json_bytes=20))
    payload = b'{"asset":{"version":"2.0"},"asset":{}}'
    data = struct.pack("<4sIIII", b"glTF", 2, 20 + len(payload + b" " * (-len(payload) % 4)),
                       len(payload + b" " * (-len(payload) % 4)), 0x4E4F534A) + payload + b" " * (-len(payload) % 4)
    refused(data)


@pytest.mark.parametrize("change", [
    {"componentType": 5124}, {"type": "VEC5"}, {"count": -1}, {"count": True},
    {"normalized": "yes"}, {"normalized": True}, {"byteOffset": 1}, {"byteOffset": 100000},
    {"bufferView": 999}, {"min": [float("nan"), 0, 0]},
])
def test_accessor_metadata(change):
    fixture = Fixture()
    fixture.triangle()
    fixture.document["accessors"][0].update(change)
    refused(fixture.bytes())


@pytest.mark.parametrize("change", [{"byteStride": 2}, {"byteStride": 256}, {"byteStride": 14},
                                    {"byteStride": 8}, {"byteOffset": 1}, {"byteLength": 100000}])
def test_buffer_view_validation(change):
    fixture = Fixture()
    fixture.triangle()
    fixture.document["bufferViews"][0].update(change)
    refused(fixture.bytes())


def test_index_values_attribute_counts_and_finite_positions():
    fixture = Fixture()
    primitive = fixture.triangle()
    primitive["indices"] = fixture.array([0, 1, 3], "SCALAR", 5123, vertex=False)
    refused(fixture.bytes())
    fixture = Fixture()
    primitive = fixture.triangle()
    primitive["attributes"]["NORMAL"] = fixture.array([[0, 1, 0]] * 2)
    refused(fixture.bytes())
    fixture = Fixture()
    fixture.triangle([[0, 0, 0], [1, float("nan"), 0], [0, 1, 0]])
    refused(fixture.bytes())


@pytest.mark.parametrize("component", [5120, 5121, 5122, 5123])
def test_normalized_integer_uvs(component):
    fixture = Fixture()
    primitive = fixture.triangle()
    dtype = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16}[component]
    info = np.iinfo(dtype)
    uv = [[info.min, info.max], [0, 0], [info.max, info.min]]
    primitive["attributes"]["TEXCOORD_0"] = fixture.array(uv, "VEC2", component, normalized=True)
    fixture.document["extensionsUsed"] = ["KHR_mesh_quantization"]
    model = reader.read_model(fixture.bytes())
    expected = np.maximum(np.array(uv, dtype=float) / info.max, -1)
    np.testing.assert_allclose(model.parts[0].uv0, expected)


@pytest.mark.parametrize("component", [5120, 5122])
def test_normalized_integer_normals(component):
    fixture = Fixture()
    primitive = fixture.triangle()
    maximum = 127 if component == 5120 else 32767
    primitive["attributes"]["NORMAL"] = fixture.array([[0, maximum, 0]] * 3, "VEC3", component, normalized=True)
    fixture.document["extensionsUsed"] = ["KHR_mesh_quantization"]
    np.testing.assert_allclose(reader.read_model(fixture.bytes()).parts[0].normals, [[0, 1, 0]] * 3)


def test_unnormalized_quantized_positions_keep_integer_values_before_transform():
    fixture = Fixture()
    primitive = fixture.triangle()
    primitive["attributes"]["POSITION"] = fixture.array([[0, 0, 0], [100, 0, 0], [0, 100, 0]], component=5122)
    fixture.document["extensionsUsed"] = ["KHR_mesh_quantization"]
    fixture.document["nodes"][0]["scale"] = [0.01, 0.01, 0.01]
    np.testing.assert_allclose(reader.read_model(fixture.bytes()).parts[0].positions,
                               [[0, 0, 0], [1, 0, 0], [0, 1, 0]])
    fixture.document.pop("extensionsUsed")
    refused(fixture.bytes())


def test_interleaved_attributes_and_zero_initialized_accessor():
    fixture = Fixture()
    primitive = fixture.triangle()
    rows = np.array([[0, 0, 0, 0, 1, 0], [1, 0, 0, 0, 1, 0], [0, 0, 1, 0, 1, 0]], dtype="<f4")
    view = fixture.data(rows.tobytes(), stride=24, target=34962)
    fixture.document["accessors"][0]["bufferView"] = view
    normals = deepcopy(fixture.document["accessors"][0])
    normals["byteOffset"] = 12
    fixture.document["accessors"].append(normals)
    primitive["attributes"]["NORMAL"] = len(fixture.document["accessors"]) - 1
    model = reader.read_model(fixture.bytes())
    np.testing.assert_allclose(model.parts[0].normals, [[0, 1, 0]] * 3)
    accessor = fixture.document["accessors"][0]
    accessor.pop("bufferView")
    assert not reader.read_model(fixture.bytes()).parts[0].positions.any()


@pytest.mark.parametrize("feature", ["skin", "morph", "sparse"])
def test_refused_features(feature):
    fixture = Fixture()
    primitive = fixture.triangle()
    if feature == "skin":
        fixture.document["skins"] = [{}]
    elif feature == "morph":
        primitive["targets"] = [{}]
    else:
        fixture.document["accessors"][0]["sparse"] = {}
    refused(fixture.bytes(), "gltf_feature_unsupported")


@pytest.mark.parametrize("extension", ["KHR_draco_mesh_compression", "EXT_meshopt_compression",
                                     "KHR_texture_basisu", "EXT_texture_webp", "VENDOR_unknown"])
def test_required_extensions(extension):
    fixture = Fixture()
    fixture.triangle()
    fixture.document["extensionsUsed"] = fixture.document["extensionsRequired"] = [extension]
    refused(fixture.bytes(), "gltf_extension_required")


def test_optional_extensions_and_rest_pose_warn():
    fixture = Fixture()
    fixture.triangle()
    fixture.document.update(extensionsUsed=["KHR_materials_clearcoat", "VENDOR_unknown"], animations=[{}])
    model = reader.read_model(fixture.bytes())
    assert len(model.warnings) == 3


def test_texture_transform_and_nonzero_channel_policy():
    fixture = textured_box()
    info = fixture.document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]
    info["extensions"] = {"KHR_texture_transform": {"offset": [0.2, 0.3], "scale": [2, 3], "rotation": math.pi/2}}
    fixture.document["extensionsUsed"] = ["KHR_texture_transform"]
    result = reader.read_model(fixture.bytes())
    np.testing.assert_allclose(result.parts[0].uv0[:3], [[0.2, 0.3], [0.2, 2.3], [-2.8, 2.3]], atol=1e-6)
    info["extensions"]["KHR_texture_transform"]["texCoord"] = 1
    result = reader.read_model(fixture.bytes())
    assert result.materials[0]["texture"] is None
    assert any("non-zero" in warning for warning in result.warnings)


def test_legacy_material_emission_and_unlit():
    fixture = textured_box()
    material = fixture.document["materials"][0]
    material["emissiveFactor"] = [0.1, 0.2, 0.3]
    material["extensions"] = {
        "KHR_materials_pbrSpecularGlossiness": {"diffuseFactor": [0.2, 0.3, 0.4, 0.5],
                                               "diffuseTexture": {"index": 0}, "glossinessFactor": 0.7},
        "KHR_materials_emissive_strength": {"emissiveStrength": 4},
        "KHR_materials_unlit": {},
    }
    fixture.document["extensionsUsed"] = list(material["extensions"])
    result = reader.read_model(fixture.bytes()).materials[0]
    assert result["baseColor"] == [0.2, 0.3, 0.4, 0.5]
    assert result["roughness"] == pytest.approx(0.3) and result["metalness"] == 0
    np.testing.assert_allclose(result["emissive"], [0.4, 0.8, 1.2])
    assert result["unlit"] is True


def test_depth_first_instances_default_scene_mirror_and_inverse_transpose():
    fixture = Fixture()
    primitive = fixture.triangle()
    primitive["attributes"]["NORMAL"] = fixture.array([[1/math.sqrt(2), 1/math.sqrt(2), 0]] * 3)
    fixture.document["nodes"] = [{"translation": [2, 0, 0], "children": [2]},
                                  {"mesh": 0, "name": "second"},
                                  {"mesh": 0, "scale": [-2, 1, 1], "name": "first"}]
    fixture.document["scenes"] = [{"nodes": [0, 1]}, {"nodes": [1]}]
    fixture.document.pop("scene")
    result = reader.read_model(fixture.bytes())
    assert [p.key for p in result.parts] == ["p0", "p1"]
    assert [p.node for p in result.parts] == ["first", "second"]
    np.testing.assert_allclose(result.parts[0].positions, [[2, 0, 0], [2, 0, 1], [0, 0, 0]])
    np.testing.assert_array_equal(result.parts[0].indices, [[0, 2, 1]])
    np.testing.assert_allclose(result.parts[0].normals, [[-1/math.sqrt(5), 2/math.sqrt(5), 0]] * 3, atol=1e-6)
    fixture.document["scene"] = 1
    assert len(reader.read_model(fixture.bytes()).parts) == 1


@pytest.mark.parametrize("kind", ["cycle", "singular", "bad_child", "duplicate_child", "matrix_and_trs", "bad_quaternion"])
def test_graph_validation(kind):
    fixture = Fixture()
    fixture.triangle()
    node = fixture.document["nodes"][0]
    if kind == "cycle":
        node["children"] = [0]
    elif kind == "singular":
        node["scale"] = [1, 0, 1]
    elif kind == "bad_child":
        node["children"] = [55]
    elif kind == "duplicate_child":
        fixture.document["nodes"].append({})
        node["children"] = [1, 1]
    elif kind == "matrix_and_trs":
        node.update(matrix=np.eye(4).ravel().tolist(), translation=[0, 0, 0])
    else:
        node["rotation"] = [0, 0, 0, 0]
    refused(fixture.bytes())


def test_depth_and_instancing_budgets_precede_array_reads(monkeypatch):
    fixture = Fixture()
    fixture.triangle()
    fixture.document["nodes"] = [{"children": [1]}, {"children": [2]}, {"mesh": 0}]
    refused(fixture.bytes(), "gltf_too_complex", limits=replace(limits.DEFAULT_LIMITS, depth=2))
    fixture.document["nodes"] = [{"mesh": 0}, {"mesh": 0}]
    fixture.document["scenes"][0]["nodes"] = [0, 1]
    monkeypatch.setattr(module("accessors").Accessors, "read", lambda *a: pytest.fail("allocated before budget"))
    for changed in ({"triangles": 1}, {"vertices": 5}, {"primitives": 1}, {"nodes": 1}):
        refused(fixture.bytes(), "gltf_too_complex", limits=replace(limits.DEFAULT_LIMITS, **changed))


@pytest.mark.parametrize("mode,expected", [(4, [[0, 1, 2], [3, 4, 5]]),
                                         (5, [[0, 1, 2], [2, 1, 3], [2, 3, 4], [4, 3, 5]]),
                                         (6, [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 5]])])
def test_primitive_modes(mode, expected):
    fixture = Fixture()
    fixture.triangle([[i, 0, i % 2] for i in range(6)], mode=mode)
    np.testing.assert_array_equal(reader.read_model(fixture.bytes()).parts[0].indices, expected)


def test_dropped_lines_stable_keys_two_materials_units_and_axis_hint():
    fixture = Fixture()
    primitive = fixture.triangle(mode=1)
    fixture.triangle([[0, 0, 0], [100, 0, 0], [0, 100, 0]])
    fixture.document["materials"] = [{"name": "line"}, {"name": "triangle"}]
    primitive["material"] = 0
    fixture.document["meshes"][1]["primitives"][0]["material"] = 1
    fixture.document["asset"]["generator"] = "Z-up fixture"
    result = summary_module.build_summary(reader.read_model(fixture.bytes()))
    assert result["parts"][0]["key"] == "p1"
    assert result["parts"][0]["name"] == "triangle"
    assert result["unitGuesses"][1]["sizeMeters"]["width"] == 1
    assert result["upAxisHint"]["suggested"] == "+Z"
    assert result["warnings"]


@pytest.mark.parametrize("change", [{"image_side": 4}, {"image_pixels": 32}, {"total_image_pixels": 32}, {"images": 0}])
def test_image_budgets(change):
    code = "gltf_too_complex" if "images" in change else "image_unsafe"
    refused(textured_box().bytes(), code, limits=replace(limits.DEFAULT_LIMITS, **change))


def test_aggregate_image_budget():
    fixture = textured_box()
    fixture.image(image_bytes())
    refused(fixture.bytes(), "image_unsafe", limits=replace(limits.DEFAULT_LIMITS, total_image_pixels=100))


@pytest.mark.parametrize("data", [b"bad image", b"\x89PNG\r\n\x1a\nbroken", b"\xff\xd8\xffbroken"])
def test_bad_image_magic_and_decode(data):
    fixture = Fixture()
    fixture.triangle()
    fixture.image(data)
    refused(fixture.bytes(), "image_unsafe")


def test_animated_image_refused():
    output = BytesIO()
    first, second = Image.new("RGBA", (4, 4), "red"), Image.new("RGBA", (4, 4), "blue")
    first.save(output, format="PNG", save_all=True, append_images=[second], duration=100, loop=0)
    first.close()
    second.close()
    fixture = Fixture()
    fixture.triangle()
    fixture.image(output.getvalue())
    refused(fixture.bytes(), "image_unsafe")


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_downsize_metadata_strip_and_opaque_reencode(format):
    fixture = Fixture()
    fixture.triangle()
    fixture.image(image_bytes("RGB", (513, 300), (20, 30, 40), format=format))
    model = reader.read_model(fixture.bytes(), texture_max_px=256)
    image = model.images[0]
    assert image.width == 256 and image.height <= 256 and image.source_width == 513
    assert image.mime_type == "image/jpeg"
    with Image.open(BytesIO(image.data)) as decoded:
        assert decoded.format == "JPEG" and not decoded.getexif()
        assert "icc_profile" not in decoded.info


def test_images_decode_and_downsize_sequentially(monkeypatch):
    fixture = Fixture()
    fixture.triangle()
    fixture.image(image_bytes())
    fixture.image(image_bytes())
    events = []
    original_open, original_thumbnail = Image.open, Image.Image.thumbnail

    def opened(*args, **kwargs):
        events.append("open")
        return original_open(*args, **kwargs)

    def resized(self, *args, **kwargs):
        events.append("downsize")
        return original_thumbnail(self, *args, **kwargs)

    monkeypatch.setattr(Image, "open", opened)
    monkeypatch.setattr(Image.Image, "thumbnail", resized)
    reader.read_model(fixture.bytes())
    assert events == ["open", "downsize", "open", "downsize"]


def test_licence_conflicts_and_untrusted_text_are_bounded():
    result = licence.parse_licence([("license.txt", "* title: A\n* license type: CC BY 4.0")],
                                  {"extras": {"title": "B", "license": "CC BY-NC-SA 4.0",
                                              "source": "javascript:alert(1)", "author": "A\u202eB\x00"}})
    assert result["class"] == "unknown" and result["conflicts"]
    assert result["sourceUrl"] == "" and result["author"] == "AB"
    result = licence.parse_licence([], {"copyright": "Copyright Test. CC BY 4.0"})
    assert result["class"] == "cc-by"
    result = licence.parse_licence([], {"extras": {"license": "https://creativecommons.org/licenses/by-nc-nd/4.0/"}})
    assert result["class"] == "cc-by-nc-nd"


def test_large_summary_is_paged_and_json_serializable():
    fixture = Fixture()
    fixture.triangle()
    fixture.document["nodes"] = [{"mesh": 0, "name": "\u65e5" * 80, "translation": [i, 0, 0]} for i in range(130)]
    fixture.document["scenes"][0]["nodes"] = list(range(130))
    model = reader.read_model(fixture.bytes(), "name\x00")
    first = summary_module.build_summary(model)
    protocol.validate_summary(first)
    assert first["partsTotal"] == 130 and 0 < len(first["parts"]) <= 64
    second = summary_module.build_summary(model, parts_offset=first["nextPartsOffset"], parts_limit=2)
    assert second["parts"][0]["key"] == "p" + str(first["nextPartsOffset"])
    assert len(second["parts"]) == 2
    with pytest.raises(ModelImportError):
        summary_module.build_summary(model, parts_offset=-1)


def test_image_magic_wins_over_resource_extension():
    fixture = Fixture()
    fixture.triangle()
    fixture.document["images"] = [{"uri": "texture.data", "mimeType": "application/octet-stream"}]
    payload = unzip_model(fixture.document, bytes(fixture.blob), resources={"pack/texture.data": image_bytes()})
    assert len(reader.read_model(payload).images) == 1


def test_unreferenced_non_license_file_refused():
    fixture = Fixture()
    fixture.triangle()
    payload = unzip_model(fixture.document, bytes(fixture.blob), resources={"pack/unrelated.exe": b"ignored"})
    refused(payload, "model_format_unsupported")


@pytest.mark.parametrize("component", [5121, 5123])
def test_unsigned_normals_are_not_valid_quantized_normals(component):
    fixture = Fixture()
    primitive = fixture.triangle()
    primitive["attributes"]["NORMAL"] = fixture.array([[0, 1, 0]] * 3, component=component, normalized=True)
    fixture.document["extensionsUsed"] = ["KHR_mesh_quantization"]
    refused(fixture.bytes())


def test_material_budget_and_invalid_scalars():
    fixture = textured_box()
    refused(fixture.bytes(), "gltf_too_complex", limits=replace(limits.DEFAULT_LIMITS, materials=0))
    fixture.document["materials"][0]["pbrMetallicRoughness"]["roughnessFactor"] = True
    refused(fixture.bytes())


def test_deep_disconnected_graph_and_matrix_transform():
    fixture = Fixture()
    fixture.triangle()
    transform = np.eye(4)
    transform[:3, 3] = [4, 5, 6]
    fixture.document["nodes"][0]["matrix"] = transform.T.ravel().tolist()
    result = reader.read_model(fixture.bytes())
    np.testing.assert_allclose(result.parts[0].positions[0], [4, 5, 6])
    fixture.document["nodes"].extend([{"children": [2]}, {"children": [3]}, {}])
    refused(fixture.bytes(), "gltf_too_complex", limits=replace(limits.DEFAULT_LIMITS, depth=2))


def test_image_dimensions_are_checked_before_decode(monkeypatch):
    fixture = Fixture()
    fixture.triangle()
    fixture.image(image_bytes("RGB", (8193, 1), "red"))
    monkeypatch.setattr(Image.Image, "thumbnail", lambda *a, **k: pytest.fail("decoded oversized image"))
    refused(fixture.bytes(), "image_unsafe")


def test_adversarial_metadata_still_has_a_bounded_page():
    fixture = Fixture()
    primitive = fixture.triangle()
    fixture.document["materials"] = [{"name": "\u65e5" * 80} for _ in range(64)]
    primitive["material"] = 0
    fixture.document["asset"]["extras"] = {key: "\u65e5" * 300 for key in ("title", "author", "license")}
    model = reader.read_model(fixture.bytes())
    model.warnings = ["\u65e5" * 300 for _ in range(20)]
    value = summary_module.build_summary(model)
    protocol.validate_summary(value)
    assert value["parts"] and value["materialsTotal"] == 64
    assert len(module("validation").json_bytes(value)) <= 48 * 1024
