"""The ribbon's pattern math and its Python port give the same numbers (docs/sage-ribbon-tools-plan.md, R1, R2,
R4).

tests/pattern_parity_runner.js runs static/facility_layout_patterns.js (the ribbon's builders) on the shared
fixture; layout_patterns.py runs on the same input. Every case must match: the same seed items, the same copies or
moves (every number within 1e-9) and the same refusals, word for word. Node runs here only, never in the app.
"""
import itertools
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ai_inspector.facility_layout import layout_patterns as patterns

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/facility_layout/pattern_parity/factory.json"
RUNNER = ROOT / "tests/pattern_parity_runner.js"
STRICT = {"expandZones": True, "includeZones": True, "strictGeometry": True}  # the command adapter's, for patterns
CELL = {"expandZones": False, "includeZones": False, "strictGeometry": True}  # and for cells
PERIMETER = {"expandZones": True, "includeZones": False, "strictGeometry": True}  # a zone's contents, not the zone
PYTHON_ONLY = {"pathPoint", "pathTangent", "pathOffset"}  # the port's extra path sample per move
MILLS = [f"pl-mill-{index}" for index in range(1, 6)]
WORKSPACE = {"expandZones": True, "includeZones": False}  # the workspace's seed for a stack or surface stack
DESK = {"surfaceId": "worktop", "label": "Desk worktop", "localFrame": {
    "origin": {"x": 0.0, "y": 0.74, "z": 0.05}, "xAxis": {"x": 1, "y": 0, "z": 0}, "zAxis": {"x": 0, "y": 0, "z": 1},
    "normal": {"x": 0, "y": 1, "z": 0}}, "bounds": {"minimumX": -0.68, "maximumX": 0.68, "minimumZ": -0.33,
                                                    "maximumZ": 0.43}, "allowedSides": ["above"],
        "evidenceStatus": "derived"}


def fixture():
    return json.loads(FIXTURE.read_bytes())


def stack_fixture():
    """The fixture with desks whose published worktops are square, turned a quarter, or tilted (refused), a stack,
    loose tools and an item of an asset not in the library."""
    data = fixture()

    def asset(asset_id, surfaces):
        return {"assetId": asset_id, "assetDefinitionRevision": "rev-" + asset_id, "displayName": asset_id,
                "definition": {"geometry": {"aabb": {"minimum": {"x": -0.7, "y": 0, "z": -0.4},
                                                     "maximum": {"x": 0.7, "y": 0.75, "z": 0.4}}}},
                "supportSurfaces": surfaces}

    turned = {**DESK, "surfaceId": "turned-top", "allowedSides": ["above", "below"], "localFrame": {
        **DESK["localFrame"], "xAxis": {"x": 0, "y": 0, "z": -1}, "zAxis": {"x": 1, "y": 0, "z": 0}}}
    tilted = {**DESK, "surfaceId": "tilted-top", "localFrame": {**DESK["localFrame"],
                                                                 "xAxis": {"x": 1, "y": 0.5, "z": 0}}}
    data["catalog"] += [asset("asset-desk", [DESK]), asset("asset-turned-desk", [turned]),
                        asset("asset-tilted-desk", [tilted])]

    def placed(placement_id, asset_id, x, z, yaw=0, y=0, relation=None, revision=None):
        half = math.radians(yaw) / 2
        return {"placementId": placement_id, "assetId": asset_id,
                "assetDefinitionRevision": revision or "rev-" + asset_id,
                "transform": {"position": {"x": x, "y": y, "z": z},
                              "quaternion": {"x": 0, "y": math.sin(half), "z": 0, "w": math.cos(half)}, "scale": 1},
                "positionMode": "manual", "snapRelationship": relation, "metadata": {"instanceLabel": placement_id}}

    stack = {"family": "vertical_stack", "stackId": "stack-crates", "count": 2, "gapMeters": 0,
             "itemHeightMeters": 0.9, "evidenceStatus": "unverified"}
    data["layout"]["placements"] += [
        placed("pl-desk-1", "asset-desk", 60, 5), placed("pl-desk-2", "asset-turned-desk", 64, 5, yaw=90),
        placed("pl-desk-3", "asset-tilted-desk", 68, 5), placed("pl-desk-4", "asset-desk", 72, 5, yaw=30),
        placed("pl-tool-1", "asset-vise", 61, 7, revision="rev-vise"),
        placed("pl-tool-2", "asset-vise", 62, 7, yaw=90, revision="rev-vise"),
        placed("pl-crate-0", "asset-box", 34, 12, relation={**stack, "level": 0}, revision="rev-box"),
        placed("pl-crate-1", "asset-box", 34, 12, y=0.9, relation={**stack, "level": 1}, revision="rev-box"),
        placed("pl-unknown", "asset-none", 80, 5)]
    return data


def linear_cases():
    seeds = {
        "bench and vise": ["pl-bench-1", "pl-vise-1"], "one mill": ["pl-mill-1"], "workstation zone": ["zn-ws-1"],
        "marking": ["mk-1"], "scaled box": ["pl-box-1"], "mixed": ["pl-bench-1", "pl-vise-1", "mk-1"],
        "turned lathe": ["pl-lathe-1"], "nothing": ["pl-none"],
    }
    options = [{"count": 6, "pitch": 2.5, "angleDegrees": 0}, {"count": 2, "pitch": 0.5, "angleDegrees": 90},
               {"count": 3, "pitch": 3.3333, "angleDegrees": 270}, {"count": 4, "pitch": 1.25, "angleDegrees": -45},
               {"count": 50, "pitch": 4, "angleDegrees": 33.3}, {"count": 5, "pitch": 2, "angleDegrees": 400},
               {"pitch": 2}, {"count": 3}, {}, {"count": 1, "pitch": 2}, {"count": 51, "pitch": 2},
               {"count": 3, "pitch": 0}, {"count": 3, "pitch": -1}, {"count": 2.4, "pitch": 1}, {"count": None}]
    cases = []
    for (label, ids), option in itertools.product(seeds.items(), options):
        for collect in (STRICT, {}):
            cases.append({"name": f"linear {label} {option} {collect}", "builder": "linear", "ids": ids,
                          "collect": collect, "options": option})
    cases.append({"name": "capacity", "builder": "linear", "ids": MILLS, "collect": STRICT,
                  "options": {"count": 50, "pitch": 5}})
    cases.append({"name": "stale revision", "builder": "linear", "ids": ["pl-stale-1"], "collect": STRICT,
                  "options": {"count": 3, "pitch": 5}})
    return cases


def cell_cases():
    seeds = {"five mills": MILLS, "three mills": MILLS[:3], "two mills": MILLS[:2],
             "mixed seven": [*MILLS, "pl-lathe-1", "pl-box-1"]}
    shapes = [*patterns.CELL_SHAPES, "bogus"]
    orientations = [*patterns.CELL_ORIENTATIONS, "bogus"]
    cases = []
    for (label, ids), shape, orientation in itertools.product(seeds.items(), shapes, orientations):
        cases.append({"name": f"cell {label} {shape} {orientation}", "builder": "cell", "ids": ids, "collect": CELL,
                      "options": {"shape": shape, "orientation": orientation}})
    sized = [{"width": 20, "depth": 14}, {"gap": 0}, {"gap": 2.5, "rows": 3}, {"rows": 1}, {"rows": 2},
             {"angleDegrees": 90}, {"angleDegrees": -30, "invertU": True}, {"angleDegrees": 225, "gap": 1.5},
             {"invertU": True}, {"width": 40, "depth": 9, "rows": 2}]
    for (label, ids), shape, option in itertools.product(seeds.items(), shapes[:10], sized):
        cases.append({"name": f"cell {label} {shape} {option}", "builder": "cell", "ids": ids, "collect": CELL,
                      "options": {"shape": shape, "orientation": "face-center", **option}})
    refused = {"one item": (["pl-mill-1"], {}), "locked": (["pl-mill-1", "pl-locked-1"], {}),
               "too small": (MILLS, {"width": 5, "depth": 5}), "no rows": (MILLS, {"rows": 0}),
               "too many rows": (MILLS, {"rows": 99}), "zero width": (MILLS, {"width": 0}),
               "negative depth": (MILLS, {"depth": -3})}
    for label, (ids, option) in refused.items():
        cases.append({"name": f"cell refused {label}", "builder": "cell", "ids": ids, "collect": CELL,
                      "options": {"shape": "u", **option}})
    return cases


PATTERN_SEEDS = {
    "bench and vise": ["pl-bench-1", "pl-vise-1"], "one mill": ["pl-mill-1"], "workstation zone": ["zn-ws-1"],
    "marking": ["mk-1"], "mixed": ["pl-bench-1", "pl-vise-1", "mk-1"], "turned lathe": ["pl-lathe-1"],
    "five mills": MILLS, "nothing": ["pl-none"],
}


def circular_cases():
    options = [{"count": 6}, {"count": 4, "centerX": 0, "centerZ": 0},
               {"count": 5, "sweepDegrees": 180, "rotateWithPattern": True, "centerX": 10, "centerZ": 30},
               {"count": 8, "rotateWithPattern": True}, {"count": 3, "sweepDegrees": 90},
               {"count": 2, "sweepDegrees": 360}, {"count": 7, "sweepDegrees": 359.5, "rotateWithPattern": True},
               {"count": 48, "rotateWithPattern": True, "centerX": -4.25, "centerZ": 12.5}, {},
               {"count": 3, "rotateWithPattern": "yes"}, {"count": 3, "centerX": "x", "centerZ": None},
               {"count": 1}, {"count": 51}, {"sweepDegrees": 400}, {"sweepDegrees": 0}, {"sweepDegrees": -10},
               {"count": None}]
    return [{"name": f"circular {label} {option}", "builder": "circular", "ids": ids, "collect": STRICT,
             "options": option} for (label, ids), option in itertools.product(PATTERN_SEEDS.items(), options)]


def perimeter_cases():
    options = [{}, {"shape": "square", "widthCount": 3}, {"widthCount": 2, "depthCount": 3, "clearGap": 0.5},
               {"angleDegrees": 30, "clearGap": 1}, {"widthCount": 1, "depthCount": 1},
               {"shape": "square", "widthCount": 4, "depthCount": 9}, {"angleDegrees": -90, "widthCount": 3},
               {"angleDegrees": 200, "depthCount": 2, "clearGap": 0.25}, {"widthCount": 50, "depthCount": 50},
               {"widthCount": 0}, {"widthCount": 51}, {"clearGap": -1}, {"depthCount": 2.5}]
    return [{"name": f"perimeter {label} {option}", "builder": "perimeter", "ids": ids, "collect": PERIMETER,
             "options": option} for (label, ids), option in itertools.product(PATTERN_SEEDS.items(), options)]


def mirror_cases():
    lines = [((30, 0), (30, 40)), ((0, 12), (60, 12)), ((0, 0), (10, 10)), ((7.25, -3), (2.5, 19.75)),
             ((-1, 50), (-1, -50))]
    options = [{"axisStart": {"x": a[0], "z": a[1]}, "axisEnd": {"x": b[0], "z": b[1]}} for a, b in lines]
    options += [{"axisStart": {"x": 5, "z": 5}, "axisEnd": {"x": 5, "z": 5}}, {},
                {"axisStart": {"x": "a", "z": 1}, "axisEnd": {"x": 1, "z": 1}},
                {"axisStart": {"x": 1, "z": 1}, "axisEnd": {"x": 1 + 1e-10, "z": 1}}]
    return [{"name": f"mirror {label} {option}", "builder": "mirror", "ids": ids, "collect": STRICT,
             "options": option} for (label, ids), option in itertools.product(PATTERN_SEEDS.items(), options)]


def stack_cases():
    seeds = {"mill": ["pl-mill-1"], "box": ["pl-box-1"], "turned lathe": ["pl-lathe-1"], "stale": ["pl-stale-1"],
             "vise on a bench": ["pl-vise-1"], "desk": ["pl-desk-2"], "two": MILLS[:2], "zone": ["zn-ws-1"],
             "marking": ["mk-1"], "stacked": ["pl-crate-0"], "unknown asset": ["pl-unknown"]}
    options = [{"count": 3}, {"count": 2, "gap": 0.25}, {"count": 50}, {"count": 51}, {"count": 1}, {},
               {"count": "4", "gap": -1}, {"count": 2.5, "gap": 0.1234567}, {"stackId": "custom", "count": 2}]
    cases = [{"name": f"stack {label} {option}", "builder": "stack", "ids": ids, "collect": WORKSPACE,
              "options": option} for (label, ids), option in itertools.product(seeds.items(), options)]
    cases.append({"name": "stack strict stale", "builder": "stack", "ids": ["pl-stale-1"], "collect": STRICT,
                  "options": {"count": 2}})
    return cases


def surface_cases():
    seeds = {"bench and box": ["pl-bench-1", "pl-box-1"], "desk and tools": ["pl-desk-1", "pl-tool-1", "pl-tool-2"],
             "turned desk and tools": ["pl-desk-2", "pl-tool-2", "pl-tool-1"],
             "tilted desk": ["pl-desk-3", "pl-tool-1"], "desk at 30 degrees": ["pl-desk-4", "pl-tool-1", "pl-box-1"],
             "desk alone": ["pl-desk-1"], "stacked child": ["pl-desk-1", "pl-crate-1"],
             "locked child": ["pl-desk-1", "pl-locked-1", "pl-tool-1"], "mills": MILLS[:3],
             "unknown child": ["pl-desk-1", "pl-unknown"], "marking": ["pl-desk-1", "mk-1", "pl-tool-1"]}
    options = [{}, {"supportPlacementId": "pl-desk-1", "surfaceId": "worktop"}, {"surfaceId": "worktop"},
               {"surfaceId": "turned-top", "side": "below", "gap": 0.02}, {"surfaceId": "worktop", "side": "below"},
               {"surfaceId": "tilted-top"}, {"gap": 0.1, "itemGap": 0.2, "inset": 0.1}, {"inset": 2},
               {"gap": -1}, {"surfaceId": "nope", "attachmentId": "custom"}, {"supportPlacementId": "pl-locked-1"},
               {"supportPlacementId": "pl-none"}, {"surfaceId": "top", "itemGap": 0}]
    return [{"name": f"surface {label} {option}", "builder": "surface", "ids": ids, "collect": WORKSPACE,
             "options": option} for (label, ids), option in itertools.product(seeds.items(), options)]


CASES = {"linear": linear_cases, "cell": cell_cases, "circular": circular_cases, "perimeter": perimeter_cases,
         "mirror": mirror_cases, "stack": stack_cases, "surface": surface_cases}
EXERCISED = {"linear": (100, 10), "cell": (100, 10), "circular": (60, 30), "perimeter": (60, 30),
             "mirror": (30, 20), "stack": (25, 40), "surface": (30, 50)}


def python_side(data, case):
    try:
        seed = patterns.collect_selection(data["layout"], data["catalog"], case["ids"], case["collect"])
        build = {"linear": patterns.build_linear_pattern, "cell": patterns.build_cell_layout,
                 "circular": patterns.build_circular_pattern, "perimeter": patterns.build_rectangular_perimeter,
                 "mirror": patterns.build_mirror, "stack": patterns.build_vertical_stack,
                 "surface": patterns.build_surface_stack}[case["builder"]]
        # JSON null stays None, which reads as 0 here as Number(null) does in JS.
        return {"ok": True, "seed": seed, "result": build(seed, dict(case["options"]))}
    except patterns.PatternError as error:
        return {"ok": False, "error": str(error)}


def node_side(data, cases):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    payload = json.dumps({"layout": data["layout"], "catalog": data["catalog"], "cases": cases}).encode("utf-8")
    flags = 0x08000000 if sys.platform == "win32" else 0  # no console window on the user's screen
    done = subprocess.run([node, str(RUNNER)], input=payload, capture_output=True, timeout=120, cwd=ROOT,
                          creationflags=flags)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    return json.loads(done.stdout)


def same(js, py, path="", tolerance=1e-9):
    """JS values against Python's: numbers within the tolerance, NaN as JSON's null, the port's extras ignored."""
    if isinstance(py, float) and math.isnan(py):
        assert js is None, path
        return
    if isinstance(js, bool) or isinstance(py, bool):
        assert js == py, path
        return
    if isinstance(js, (int, float)) and isinstance(py, (int, float)):
        assert abs(js - py) <= tolerance, f"{path}: js {js!r} python {py!r}"
        return
    if isinstance(js, dict) and isinstance(py, dict):
        assert set(js) == set(py) - PYTHON_ONLY, f"{path}: keys js {sorted(js)} python {sorted(py)}"
        for key in js:
            same(js[key], py[key], f"{path}.{key}", tolerance)
        return
    if isinstance(js, list) and isinstance(py, list):
        assert len(js) == len(py), f"{path}: {len(js)} items in js, {len(py)} in python"
        for index, (left, right) in enumerate(zip(js, py)):
            same(left, right, f"{path}[{index}]", tolerance)
        return
    assert js == py, f"{path}: js {js!r} python {py!r}"


@pytest.mark.parametrize("group", list(CASES))
def test_the_port_gives_the_ribbons_numbers(group):
    data = stack_fixture() if group in ("stack", "surface") else fixture()
    cases = CASES[group]()
    results = node_side(data, cases)
    assert len(results) == len(cases)
    worked = refused = 0
    for case, js in zip(cases, results):
        py = python_side(data, case)
        assert js["ok"] == py["ok"], (case["name"], js.get("error"), py.get("error"))
        if not js["ok"]:
            assert js["error"] == py["error"], case["name"]
            refused += 1
            continue
        same(js["seed"], py["seed"], case["name"] + " seed")
        same(js["result"], py["result"], case["name"])
        worked += 1
    # Both kinds of case are really exercised.
    assert worked > EXERCISED[group][0] and refused > EXERCISED[group][1], (worked, refused)


def test_degrees_round_like_javascript():
    """toFixed(6) rounds the exact binary value, halves away from zero; Python's round() would not."""
    assert patterns.normalize_degrees(0.0078125) == 0.007813  # an exact half in binary
    assert patterns.normalize_degrees(-90) == 270 and patterns.normalize_degrees(720.5) == 0.5
    assert patterns.normalize_degrees(-1e-12) == 360.0  # as Number((360 - 1e-12).toFixed(6)) is
    assert math.copysign(1, patterns.normalize_degrees(-0.0)) == 1
    assert patterns.js_round(2.5) == 3 and patterns.js_round(-2.5) == -2
