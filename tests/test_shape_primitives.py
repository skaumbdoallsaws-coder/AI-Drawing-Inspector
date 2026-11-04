"""Basic shapes BS0 (docs/sage-basic-shapes-plan.md): the shape kernel, ai_inspector/industrial_assets/primitives.py.

Every check reads the finished GLB back, the way the 3D view and the catalog see it."""
from __future__ import annotations

import json
import math
import struct

import pytest

from ai_inspector.industrial_assets import primitives as shapes
from ai_inspector.industrial_assets.artifacts import inspect_glb


def decoded(payload: bytes) -> list[dict]:
    """Each mesh's name, positions, normals, triangles and material, read from the GLB bytes."""
    doc = shapes.gltf_json(payload)
    json_length = struct.unpack_from("<I", payload, 12)[0]
    binary = payload[20 + json_length + 8:]

    def read(index):
        accessor = doc["accessors"][index]
        view = doc["bufferViews"][accessor["bufferView"]]
        code = {5126: "f", 5123: "H", 5125: "I"}[accessor["componentType"]]
        width = {"VEC3": 3, "SCALAR": 1}[accessor["type"]]
        values = struct.unpack_from(f"<{accessor['count'] * width}{code}", binary, view["byteOffset"])
        return [values[i:i + width] for i in range(0, len(values), width)] if width > 1 else list(values)
    meshes = []
    for mesh in doc["meshes"]:
        primitive = mesh["primitives"][0]
        indices = read(primitive["indices"])
        meshes.append({"name": mesh["name"], "positions": read(primitive["attributes"]["POSITION"]),
                       "normals": read(primitive["attributes"]["NORMAL"]),
                       "triangles": [indices[i:i + 3] for i in range(0, len(indices), 3)],
                       "material": doc["materials"][primitive["material"]]})
    return meshes


def flat(box):
    return tuple(box[0]) + tuple(box[1])


def column():
    """The Factory 02 column (f02_columns_build.py): an H-section 400 x 300 mm on a 500 mm base plate, 10 m high."""
    steel, plate = shapes.Mesh(), shapes.Mesh()
    for side in (-1, 1):
        inner, outer = side * 0.2 - (0.025 if side > 0 else 0), side * 0.2 + (0.025 if side < 0 else 0)
        steel.box((inner, 0.03, -0.15), (outer, 10.0, 0.15))   # the flanges
    steel.box((-0.175, 0.03, -0.007), (0.175, 10.0, 0.007))
    plate.box((-0.25, 0.0, -0.25), (0.25, 0.03, 0.25))
    return [("steel", steel, "#c3cad0"), ("base plate", plate, "#858d94")]


def every_shape():
    mesh = shapes.Mesh()
    mesh.box((-1, 0, -1), (1, 2, 1))
    mesh.box((2, 0, 0), (3, 1, 1), skip=("-y", "+x"))
    for axis, centre in (("x", (1.0, 0.0)), ("y", (0.0, 0.0)), ("z", (0.5, 0.2))):
        for sides in (4, 8, 24):
            mesh.prism(axis, centre, 0.1, -1.0, 1.0, sides=sides, caps=sides != 4, smooth=sides == 24)
    for start, end in (((0, 1, 0), (3, 1, 0)), ((0, 0, 0), (0, 3, 0)), ((0, 0, 0), (0, 0, 3)), ((0, 0, 0), (2, 1, 0)),
                       ((1, 2, 0), (0, 0, 0)), ((0, 0, 0), (1, 2, 3)), ((0, 0, 0), (0.01, 3, 0))):
        mesh.bar(start, end, 0.04, 0.06, caps=True)
    mesh.face([(0, 5, 0), (0, 5, 1), (1, 5, 1), (1, 5, 0)], (0, 1, 0))   # clockwise seen from above: turned round
    mesh.face([(0, 6, 0), (1, 6, 0), (1, 6, 1), (0, 6, 1)], (0, -1, 0))  # and the other way
    return [("all", mesh, "#808080")]


def test_every_face_winds_counter_clockwise_seen_from_the_side_its_normals_point_to():
    payload = shapes.glb(every_shape(), root="all") + b""
    checked = 0
    for mesh in decoded(payload):
        positions, normals = mesh["positions"], mesh["normals"]
        for triangle in mesh["triangles"]:
            a, b, c = (positions[i] for i in triangle)
            geometric = shapes._cross(shapes._sub(b, a), shapes._sub(c, a))
            for index in triangle:
                assert shapes._dot(geometric, normals[index]) > 0, (triangle, normals[index])
                assert abs(math.sqrt(shapes._dot(normals[index], normals[index])) - 1) < 1e-5
            checked += 1
    assert checked == every_shape()[0][1].triangles == 492


def test_the_model_s_bounding_box_is_its_declared_size():
    payload = shapes.glb(column(), root="column")
    report = shapes.verify(payload, {"width": 0.5, "depth": 0.5, "height": 10.0})
    assert report["dimensions"] == {"width": 0.5, "height": 10.0, "depth": 0.5}
    assert report["triangles"] == inspect_glb(payload).scene_triangle_count == 48
    assert shapes.size_of(column()) == pytest.approx({"width": 0.5, "height": 10.0, "depth": 0.5})
    with pytest.raises(ValueError, match="height is 10.0000 m, not the declared 9.0000 m"):
        shapes.verify(payload, {"width": 0.5, "depth": 0.5, "height": 9.0})


def test_a_model_sits_centred_on_x_and_z_with_its_base_at_y_0():
    def model():
        mesh = shapes.Mesh()
        mesh.box((2, 1, 3), (4, 2, 7))
        return [("block", mesh, "#123456")]
    with pytest.raises(ValueError, match="base is at y = 1.0000"):
        shapes.verify(shapes.glb(model(), root="block"))
    sunk = model()
    sunk[0][1].move(0, -1, 0)
    with pytest.raises(ValueError, match="not centred"):
        shapes.verify(shapes.glb(sunk, root="block"))
    placed = shapes.on_floor(model())
    assert shapes.bounds(placed) == ((-1.0, 0.0, -2.0), (1.0, 1.0, 2.0))
    assert shapes.verify(shapes.glb(placed, root="block"), {"width": 2, "height": 1, "depth": 4})["triangles"] == 12


def test_every_material_is_an_authored_finish_named_after_its_part():
    lamp = shapes.Mesh()
    lamp.prism("y", (0.0, 0.0), 0.2, 0.0, 0.02, sides=16)
    lens = shapes.Finish("#ffffff", roughness=0.3, fields={"emissiveFactor": [1, 0.97, 0.9]},
                         extras={"facilityDefaultFinish": "Lights"})
    parts = column() + [("lens", lamp, lens)]
    payload = shapes.glb(parts, root="column")
    materials = {mesh["name"]: mesh["material"] for mesh in decoded(payload)}
    assert set(materials) == {"steel", "base plate", "lens"}
    for name, material in materials.items():
        assert material["name"] == name
        assert material["extras"]["facilityAuthoredFinish"] is True
        assert material["extras"]["facilityMaterialRole"] == name
    assert materials["steel"]["pbrMetallicRoughness"] == {"baseColorFactor": shapes.linear("#c3cad0") + [1.0],
                                                          "metallicFactor": 0.0, "roughnessFactor": 0.55}
    assert materials["lens"]["emissiveFactor"] == [1, 0.97, 0.9]
    assert materials["lens"]["extras"]["facilityDefaultFinish"] == "Lights"
    assert shapes.linear("#ffffff") == [1.0, 1.0, 1.0] and shapes.linear("#000000") == [0.0, 0.0, 0.0]
    # A model whose material lost its marker is refused: the 3D view would paint it neutral gray.
    doc = shapes.gltf_json(payload)
    del doc["materials"][0]["extras"]
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    rest = payload[20 + struct.unpack_from("<I", payload, 12)[0]:]
    body = struct.pack("<I4s", len(text), b"JSON") + text + rest
    with pytest.raises(ValueError, match="without extras.facilityAuthoredFinish.*steel"):
        shapes.verify(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)


def test_thin_bars_get_four_sides_and_no_caps_and_other_shapes_count_their_faces():
    def triangles(build):
        mesh = shapes.Mesh()
        build(mesh)
        return mesh.triangles
    assert triangles(lambda m: m.bar((0, 0, 0), (1, 1, 0), 0.04)) == 8
    assert triangles(lambda m: m.bar((0, 0, 0), (1, 1, 0), 0.04, caps=True)) == 12
    assert triangles(lambda m: m.box((0, 0, 0), (1, 1, 1))) == 12
    assert triangles(lambda m: m.box((0, 0, 0), (1, 1, 1), skip=("-y",))) == 10
    assert triangles(lambda m: m.prism("x", (0, 0), 0.1, 0, 1)) == 8 * 2 + 2 * 6
    assert triangles(lambda m: m.prism("y", (0, 0), 0.1, 0, 1, sides=4, caps=False)) == 8
    # With sides a multiple of 4 the flats face the other axes, so a prism is exactly 2 * radius across them.
    mesh = shapes.Mesh()
    mesh.prism("y", (0.0, 0.0), 0.5, 0.0, 2.0, sides=24, smooth=True)
    assert flat(shapes.bounds([("tank", mesh, "#ffffff")])) == pytest.approx((-0.5, 0.0, -0.5, 0.5, 2.0, 0.5))
    # A bar's width runs across it horizontally and its height in the upright plane through it.
    mesh = shapes.Mesh()
    mesh.bar((-1, 1, 0), (1, 1, 0), 0.2, 0.4)
    assert flat(shapes.bounds([("bar", mesh, "#ffffff")])) == pytest.approx((-1, 0.8, -0.1, 1, 1.2, 0.1))
    mesh = shapes.Mesh()
    mesh.bar((0, 0, 0), (0, 3, 0), 0.2, 0.4)
    assert flat(shapes.bounds([("rod", mesh, "#ffffff")])) == pytest.approx((-0.1, 0, -0.2, 0.1, 3, 0.2))


def test_the_same_parts_always_give_the_same_bytes_and_a_valid_glb():
    first, second = shapes.glb(every_shape(), root="all"), shapes.glb(every_shape(), root="all")
    assert first == second
    info = inspect_glb(first)
    assert info.scene_triangle_count == every_shape()[0][1].triangles
    assert info.generator == shapes.GENERATOR
    doc = shapes.gltf_json(first)
    assert doc["nodes"][0] == {"children": [1], "name": "all"}
    accessor = doc["accessors"][0]
    positions = decoded(first)[0]["positions"]
    assert accessor["min"] == [min(p[k] for p in positions) for k in range(3)]
    assert accessor["max"] == [max(p[k] for p in positions) for k in range(3)]


def test_a_part_with_more_than_65535_corners_gets_32_bit_indices():
    mesh = shapes.Mesh()
    for k in range(2731):   # 24 corners a box
        mesh.box((k, 0, 0), (k + 0.5, 1, 1))
    payload = shapes.glb(shapes.on_floor([("blocks", mesh, "#808080")]), root="blocks")
    assert len(mesh.positions) > 65535
    assert shapes.gltf_json(payload)["accessors"][2]["componentType"] == 5125
    assert inspect_glb(payload).scene_triangle_count == 2731 * 12


@pytest.mark.parametrize("build, message", [
    (lambda: shapes.linear("red"), "#rrggbb"),
    (lambda: shapes.Mesh().box((0, 0, 0), (1, 0, 1)), "lo < hi"),
    (lambda: shapes.Mesh().box((0, 0, 0), (1, 1, 1), skip=("top",)), "Unknown box faces"),
    (lambda: shapes.Mesh().prism("w", (0, 0), 1, 0, 1), "axis x, y or z"),
    (lambda: shapes.Mesh().prism("x", (0, 0), 1, 0, 1, sides=2), "3 or more sides"),
    (lambda: shapes.Mesh().bar((0, 0, 0), (0, 0, 0), 0.1), "No direction"),
    (lambda: shapes.glb([("a", shapes.Mesh(), "#ffffff")], root="none"), "at least one triangle"),
    (lambda: shapes.glb(column() + [("steel", column()[0][1], "#ffffff")], root="twice"), "its own name"),
])
def test_bad_shapes_are_refused(build, message):
    with pytest.raises(ValueError, match=message):
        build()
