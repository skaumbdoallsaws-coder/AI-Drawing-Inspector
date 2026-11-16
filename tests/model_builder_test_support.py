"""Private-package test loading, without importing the application."""
from copy import deepcopy
import importlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ai_inspector/industrial_assets/model_builder"
REFERENCE = ROOT / "docs/sage-model-builder-reference"
PACKAGE_NAME = "_model_builder_tests"


def module(name):
    if PACKAGE_NAME not in sys.modules:
        spec = importlib.util.spec_from_file_location(PACKAGE_NAME, PACKAGE / "__init__.py",
                                                     submodule_search_locations=[str(PACKAGE)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE_NAME] = package
        spec.loader.exec_module(package)
    return importlib.import_module(PACKAGE_NAME + "." + name)


def shape(kind="box", **fields):
    defaults = {
        "box": {"min": [-.5, 0, -.5], "max": [.5, 1, .5]},
        "cylinder": {"from": [0, 0, 0], "to": [0, 1, 0], "radius": .5},
        "tube": {"path": [[0, 0, 0], [0, 1, 0]], "radius": .1},
        "lathe": {"profile": [[.5, 0], [.5, 1]], "center": [0, 0, 0]},
        "torus": {"center": [0, 0, 0], "radius": .5, "tubeRadius": .1},
        "sphere": {"center": [0, 0, 0], "radii": [1, 2, 3]},
        "extrude": {"profile": [[0, 0], [1, 0], [1, 1], [0, 1]], "plane": "xy", "at": 0, "depth": .2},
        "panel": {"center": [0, .5, .5025], "size": [1, 1], "facing": "+z",
                  "print": {"background": "#f0f0f0", "items": []}},
    }
    return {"id": "body", "name": "housing", "material": "paint", "shape": kind,
            **deepcopy(defaults[kind]), **deepcopy(fields)}


def recipe(*entries, **fields):
    return {"name": "Illustrative equipment", "category": "Material Handling",
            "size": {"width": 1, "height": 1, "depth": 1},
            "sizeBasis": {"kind": "typical", "note": "Generic test dimensions"},
            "materials": {"paint": {"color": "#52708a"}}, "entries": list(entries) or [shape()],
            **deepcopy(fields)}


def include(**fields):
    return {"id": "host", "name": "host", "include": "asset-built-example-" + "a" * 24,
            "revision": "b" * 64, "artifactSha256": "c" * 64, **deepcopy(fields)}


def reference(name):
    return json.loads((REFERENCE / "recipes" / (name + ".json")).read_text(encoding="utf-8"))


def gltf(payload):
    import struct
    return json.loads(payload[20:20 + struct.unpack_from("<I", payload, 12)[0]])
