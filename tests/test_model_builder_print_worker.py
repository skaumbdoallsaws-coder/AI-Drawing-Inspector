"""MB2 real-worker parity and textured-result trust boundary (run outside sandbox)."""
from hashlib import sha256
import json
from pathlib import Path
import struct

import numpy as np
import pytest

from ai_inspector.industrial_assets import model_builder_runner as host
from tests.model_builder_test_support import gltf, module, recipe, shape

kernel, printing = module("build"), module("prints")
DEPENDENCIES = Path(np.__file__).resolve().parent.parent


def printed_recipe():
    items = [{"text": "OUTBOUND", "box": [.05, .05, .95, .35], "color": "#112233", "weight": "bold"},
             {"rect": [.02, .02, .98, .98], "stroke": "#556677", "lineMm": 1, "radiusMm": 2},
             {"line": [.05, .5, .95, .5], "color": "#123456", "lineMm": 1},
             {"circle": [.75, .65, .025], "fill": "#ff0000"},
             {"barcode": [.05, .6, .4, .85], "seed": 17},
             {"stripes": [.45, .6, .65, .85], "colors": ["#ffee00", "#000000"], "angleDegrees": 45, "widthMm": 3},
             {"dots": {"area": [.75, .8, .95, .95], "pitchMm": 4, "radiusMm": .5, "color": "#000000"}}]
    return recipe(shape("panel", center=[0, .05, 0], size=[.2, .1], print={"background": "#ffffff", "items": items}),
                  size={"width": .2, "height": .1, "depth": .0025},
                  materials={"paint": {"color": "#333333", "lit": .6}})


def job(tmp_path, raw=None):
    directory = tmp_path / "job"
    directory.mkdir()
    value = printed_recipe() if raw is None else raw
    host.write_job_inputs(directory, value, categories=[value["category"]], appearance_ids=["steel"])
    return directory, value


def test_prints_are_deterministic_twice_and_in_a_real_isolated_worker(tmp_path, monkeypatch):
    directory, raw = job(tmp_path)
    first = kernel.build_model(raw)
    second = kernel.build_model(raw)
    assert first.glb == second.glb and first.prints["body"].data == second.prints["body"].data
    seen = []
    original = printing.font_bytes
    def checked(directory=None):
        seen.append(directory)
        return original(directory)
    monkeypatch.setattr(printing, "font_bytes", checked)
    copied = kernel.build_model(raw, font_directory=directory / "fonts")
    assert copied.glb == first.glb and seen == [directory / "fonts"]
    result = host.run_build(directory, DEPENDENCIES)
    assert (directory / "model.glb").read_bytes() == first.glb
    assert result["images"][0]["sha256"] == sha256(first.prints["body"].data).hexdigest()
    assert result["lints"] == result["warnings"] == []
    assert {p.name for p in directory.iterdir()} == host.job_io.INPUT_NAMES | {"model.glb", "result.json"}


def test_print_lints_survive_the_worker_protocol(tmp_path):
    raw = printed_recipe()
    raw["entries"][0]["print"]["items"] = [
        {"text": "SMALL", "box": [0, 0, .001, .001], "color": "#000000"},
        {"rect": [-.1, .2, .5, .8], "fill": "#ffffff"}]
    directory, _ = job(tmp_path, raw)
    result = host.run_build(directory, DEPENDENCIES)
    assert {p["code"] for p in result["lints"]} == {"print_clipped", "print_small_text"}
    assert {p["item"] for p in result["lints"] if p["code"] == "print_clipped"} == {0, 1}


@pytest.mark.parametrize("tamper", ["image-hash", "image-size", "material-finish", "emission", "png"])
def test_host_refuses_tampered_prints_before_application_verification(tmp_path, monkeypatch, tamper):
    directory, _ = job(tmp_path)
    original = host.launch._launch
    def changed(*args, **kwargs):
        original(*args, **kwargs)
        summary = json.loads((directory / "result.json").read_bytes())
        front = next(m for m in summary["materials"] if m.get("artwork"))
        if tamper == "image-hash":
            summary["images"][0]["sha256"] = "0"*64
        elif tamper == "image-size":
            summary["images"][0]["width"] = 1025
        elif tamper == "material-finish":
            front["defaultFinish"] = {"appearanceId": "steel"}
        elif tamper == "emission":
            front["emissiveTexture"] = None
        else:
            payload = bytearray((directory / "model.glb").read_bytes())
            document = gltf(payload)
            view = document["bufferViews"][document["images"][0]["bufferView"]]
            start = 28+struct.unpack_from("<I", payload, 12)[0]+view["byteOffset"]
            payload[start+29] ^= 1  # Break IHDR CRC while keeping geometry and image dimensions intact.
            summary["images"][0]["sha256"] = sha256(payload[start:start+view["byteLength"]]).hexdigest()
            summary["outputSha256"] = sha256(payload).hexdigest()
            (directory / "model.glb").write_bytes(payload)
        (directory / "result.json").write_bytes(host.json_bytes(summary))
    monkeypatch.setattr(host.launch, "_launch", changed)
    monkeypatch.setattr(host.primitives, "verify", lambda *a, **k: pytest.fail("unvalidated print reached verifier"))
    with pytest.raises(host.ModelImportError) as caught:
        host.run_build(directory, DEPENDENCIES)
    assert caught.value.code == "model_worker_failed"
    assert not any((directory / name).exists() for name in host.job_io.OUTPUT_NAMES)


def test_extended_reader_keeps_artwork_and_the_shared_emissive_texture():
    result = kernel.build_model(printed_recipe())
    reader = module("imports").module("reader")
    restored = reader.read_model(result.glb, extended_materials=True)
    front = next(m for m in restored.materials if m.get("artwork"))
    assert front["baseColor"] == [1, 1, 1, 1]
    assert front["emissive"] == [.6, .6, .6]
    assert front["texture"] == front["emissiveTexture"]
    assert "defaultFinish" not in front
    assert len(restored.images) == 1
