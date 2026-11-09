"""Generated look-alikes used to exercise recipes, not replicas of private downloads."""
from copy import deepcopy
import math

import numpy as np

from tests.model_import_test_support import Fixture, module

RECIPE_BASE = {"importId": "mi-" + "0" * 24, "name": "Imported decor", "category": "decor"}


def recipe(**fields):
    return {**deepcopy(RECIPE_BASE), **fields}


def add_spec(shape="box", name="body", **fields):
    value = {"shape": shape, "name": name, "color": "#a07040", "position": [0, 0, 0],
             "turnDegrees": 0, "roughness": .8, "metalness": 0}
    value.update({"size": [1, 1, 1]} if shape == "box" else
                 {"radius": .1, "height": .2} if shape == "cylinder" else
                 {"radiusBottom": .1, "radiusTop": .15, "height": .2})
    value.update(fields)
    return value


def fixture_from_parts(parts):
    fixture = Fixture()
    for part, material in parts:
        primitive = fixture.triangle(part.positions, indexed=False)
        primitive["indices"] = fixture.array(part.indices.reshape(-1), "SCALAR", 5125, vertex=False)
        if part.normals is not None:
            primitive["attributes"]["NORMAL"] = fixture.array(part.normals)
        fixture.document["meshes"][-1]["name"] = part.mesh or part.name
        fixture.document["nodes"][-1]["name"] = part.node or part.name
        materials = fixture.document.setdefault("materials", [])
        primitive["material"] = len(materials)
        materials.append({"name": material["name"], "emissiveFactor": [.1, .2, .3],
                          "pbrMetallicRoughness": {"baseColorFactor": material["baseColor"],
                                                   "roughnessFactor": material["roughness"],
                                                   "metallicFactor": material["metalness"]}})
    return fixture


def solids(specs):
    return fixture_from_parts([module("simple_parts").added_part(spec, i) for i, spec in enumerate(specs)])


def mug_fixture():
    # One primitive: tapered open body plus a curved handle clear of the lowest 10%.
    body, material = module("simple_parts").added_part(add_spec("frustum", "mug", radiusBottom=.035,
                                                              radiusTop=.04, height=.095, hollow=.004), 0)
    points, normals, triangles = [], [], []
    for i in range(17):
        a = -math.pi / 2 + i * math.pi / 16
        center = np.array([.036 + .026 * math.cos(a), .049 + .032 * math.sin(a), 0])
        for j in range(8):
            b = j * math.tau / 8
            normal = np.array([math.cos(a) * math.cos(b), math.sin(a) * math.cos(b), math.sin(b)])
            points.append(center + normal * .004)
            normals.append(normal)
    for i in range(16):
        for j in range(8):
            a, b, c, d = i * 8 + j, i * 8 + (j + 1) % 8, (i + 1) * 8 + (j + 1) % 8, (i + 1) * 8 + j
            triangles.extend([[a, b, c], [a, c, d]])
    count = len(body.positions)
    body.positions = np.concatenate([body.positions, points])
    body.normals = np.concatenate([body.normals, normals])
    body.indices = np.concatenate([body.indices, np.array(triangles) + count]).astype(np.uint32)
    return fixture_from_parts([(body, material)])


def six_recipes():
    bowl = solids([add_spec("frustum", "bowl", radiusBottom=.1, radiusTop=.175, height=.08, hollow=.008),
                   add_spec("box", "fruit", size=[.2, .08, .15], position=[0, .04, 0])])
    board = solids([
        add_spec(name="baked_FLAT", size=[.41 / .85, .02, .22]),
        add_spec("cylinder", "Material.002", radius=.025, height=.32 / .85, position=[-.1, 0, 0]),
        add_spec("cylinder", "Material.003", radius=.02, height=.18, position=[.08, .02, 0]),
        add_spec("cylinder", "red_wine", radius=.015, height=.12, position=[.08, .02, 0]),
        add_spec("cylinder", "glass", radius=.025, height=.14, position=[.12, .02, .05]),
        add_spec(name="bread", size=[.1, .05, .06], position=[.02, .02, -.06]),
        add_spec(name="Material.004", size=[.01, .04, .005], position=[-.1, .08, .026]),
    ])
    board_rules = [{"select": {"material": source}, "name": name} for source, name in
                   (("Material.002", "wine bottle"), ("Material.003", "wine bottle"), ("red_wine", "wine"),
                    ("glass", "glasses"), ("bread", "bread"), ("baked_FLAT", "board"))]
    board_rules += [{"select": {"material": "Material.004"}, "name": "wine label",
                     "material": {"color": "#e8dcc4", "roughness": .8, "texture": "drop"}},
                    {"select": {"all": True}, "material": {"emissive": "off"}}]
    tree = solids([add_spec("cylinder", "olive-tree-bark", radius=.04, height=1, position=[.3, 0, -.2]),
                   add_spec(name="olive-leaves", size=[.8, .8, .7], position=[.5, .2, -.2])])
    basil = solids([add_spec("frustum", "basil", radiusBottom=.055, radiusTop=.08, height=.3)])
    vases = solids([add_spec("frustum", f"vase{i}", radiusBottom=8, radiusTop=10, height=40,
                            position=[i * 30, 0, 0]) for i in range(1, 6)])
    off = {"select": {"all": True}, "material": {"emissive": "off"}}
    return [
        ("bowl", bowl, recipe(parts=[off])),
        ("board", board, recipe(size={"scale": .85}, parts=board_rules)),
        ("mugs", mug_fixture(), recipe(size={"dimension": "height", "meters": .095},
            pivot={"parts": [{"all": True}]}, parts=[{"select": {"all": True}, "name": "mugs",
                "material": {"color": "#22272e", "roughness": .35, "texture": "drop"}}],
            copies=[{"x": -.02, "z": -.11, "turnDegrees": 20}, {"x": .015, "z": 0, "turnDegrees": -15},
                    {"x": -.01, "z": .11, "turnDegrees": 35}])),
        ("olive", tree, recipe(size={"dimension": "height", "meters": .965},
            pivot={"parts": [{"material": "olive-tree-bark"}]},
            parts=[{"select": {"material": "olive-leaves"}, "name": "olive leaves",
                    "material": {"alpha": "mask", "alphaCutoff": .5, "emissive": "off"}},
                   {"select": {"material": "olive-tree-bark"}, "name": "olive trunk",
                    "material": {"emissive": "off"}}, {"select": {"all": True}, "move": [0, .385, 0]}],
            add=[add_spec("frustum", "terracotta pot", radiusBottom=.18, radiusTop=.25,
                          height=.45, hollow=.012, color="#b4643e", roughness=.85),
                 add_spec("cylinder", "soil", radius=.234, height=.01, position=[0, .405, 0],
                          color="#3a2a1e", roughness=.95)])),
        ("basil", basil, recipe(size={"dimension": "height", "meters": .3}, parts=[off],
                               copies=[{"x": 0, "z": -.105}, {"x": .01, "z": .105, "turnDegrees": 70, "scale": .92}])),
        ("vases", vases, recipe(size={"scale": .005}, textureMaxPx=512, parts=[
            {"select": {"material": f"vase{i}"}, "name": f"vase {i}", "moveTo": position} for i, position in
            ((1, [-.34, 0, 0]), (4, [.05, 0, 0]), (3, [.38, 0, 0]), (5, [-.22, .35, 0]), (2, [.30, .35, 0]))] + [off])),
    ]


def prepare_fixture(fixture, raw_recipe=None):
    payload = fixture.bytes()
    source = module("reader").read_model(payload)
    return module("prepare").build_draft(source, recipe() if raw_recipe is None else raw_recipe, payload)
