"""Stdlib-only protocol tests, runnable with unittest in a dependency-poor sandbox."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from tests.model_builder_test_support import PACKAGE, module, recipe, shape

errors, protocol, jobs = module("errors"), module("protocol"), module("job_io")
normalize = module("recipe").normalize_recipe
BuilderError = errors.ModelBuildError
ImportErrorType = module("imports").module("errors").ModelImportError
ALLOWED = {"categories": ["Material Handling"], "appearanceIds": []}


def inputs(directory, raw=None):
    normalized = normalize(recipe() if raw is None else raw)
    (directory / "recipe.json").write_bytes(errors.json_bytes(normalized))
    (directory / "allowed.json").write_bytes(errors.json_bytes(ALLOWED))
    (directory / "includes").mkdir()
    (directory / "fonts").mkdir()
    for name in ("fonts.json", "Aileron-Regular-subset.ttf"):
        (directory / "fonts" / name).write_bytes((PACKAGE / "fonts" / name).read_bytes())
    return normalized


def sample():
    raw = normalize(recipe())
    value = {"schemaVersion": 1, "kind": "build", "engineVersion": "model-builder-1",
             "recipeSha256": protocol.digest(raw), "allowedSha256": protocol.digest(ALLOWED),
             "outputSha256": "a"*64, "outputBytes": 1024, "dimensions": dict(raw["size"]),
             "catalogDimensions": dict(raw["size"]), "shift": [0, 0, 0], "triangles": 12,
             "parts": [{"key": "p:housing#0", "name": "housing", "material": 0, "triangles": 12}],
             "partMap": {"entries": {"body": ["p:housing#0"]}, "instances": {"body[0]": ["p:housing#0"]}},
             "materials": [{"name": "paint", "baseColor": [.1, .2, .3, 1], "texture": None, "alphaMode": "OPAQUE",
                            "alphaCutoff": .5, "emissive": [0,0,0], "doubleSided": False,
                            "roughness": .6, "metalness": 0, "unlit": False}],
             "surfaces": [], "footprint": [[{"x": -.5, "z": -.5}, {"x": .5, "z": -.5},
                                           {"x": .5, "z": .5}, {"x": -.5, "z": .5}]],
             "lints": [], "warnings": [], "budgets": module("budgets").estimate(raw),
             "provenance": protocol.provenance(raw)}
    return raw, value


def recipe_60001():
    return recipe(shape("torus", id="hoops", segments=64, repeat={"count": 58, "step": [0,0,0]}),
                  shape(id="blocks", repeat={"count": 49, "step": [0,0,0]}),
                  shape("cylinder", id="pipe", segments=7, caps="start"))


class ProtocolTests(unittest.TestCase):
    def test_error_round_trips_every_code(self):
        for code in errors.MESSAGES:
            with self.subTest(code=code):
                error = BuilderError(code, "$.entries[0]", "Generic repair hint")
                self.assertEqual(errors.decode_error(errors.json_bytes(error.to_dict())).to_dict(), error.to_dict())

    def test_exact_60001_limit_and_path(self):
        with self.assertRaises(BuilderError) as caught:
            normalize(recipe_60001())
        error = errors.decode_error(errors.json_bytes(caught.exception.to_dict()))
        self.assertEqual(error.code, "budget_exceeded")
        self.assertEqual(error.path, "$.entries[2]")
        self.assertEqual(error.to_dict()["details"]["triangles"], 60001)
        self.assertEqual(error.to_dict()["details"]["limit"], 60000)

    def test_refusal_rejects_spoofed_or_unbounded_fields(self):
        base = BuilderError("budget_exceeded", "$.entries[2]", triangles=60001).to_dict()
        invalid = []
        for patch in ({"code": "model_output_too_complex"}, {"message": "untrusted"}, {"extra": True}):
            invalid.append({**deepcopy(base), **patch})
        for patch in ({"path": "not a JSON path"}, {"path": "$invalid"}, {"path": "$"+"x"*240}, {"problem": "x"*501},
                      {"problem": "bad\ntext"}, {"limit": 250000}, {"triangles": True},
                      {"triangles": 60000}, {"triangles": 30000001}, {"limit": 60000.0}):
            value = deepcopy(base)
            value["details"].update(patch)
            invalid.append(value)
        invalid.append({**deepcopy(base), "code": "schema_invalid", "message": errors.MESSAGES["schema_invalid"]})
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                errors.decode_error(errors.json_bytes(value))
        for payload in (b" "*8193, b'{"code":"schema_invalid","code":"font_missing"}', b'{"a":NaN}', b"\xff"):
            with self.assertRaises(ValueError):
                errors.decode_error(payload)

    def test_bounded_error_constructor(self):
        value = BuilderError("schema_invalid", "$."+"x"*1000, "y\n"*1000).to_dict()
        self.assertLessEqual(len(value["details"]["path"]), 240)
        self.assertLessEqual(len(value["details"]["problem"]), 500)
        self.assertNotIn("\n", value["details"]["problem"])
        errors.decode_error(errors.json_bytes(value))
        value = BuilderError("schema_invalid", "$."+"\U0001f300"*240, "\U0001f300"*500).to_dict()
        payload = errors.json_bytes(value)
        self.assertLessEqual(len(payload), errors.ERROR_BYTES)
        errors.decode_error(payload)

    def test_strict_job_inputs_and_normalized_recipe(self):
        with tempfile.TemporaryDirectory(prefix="mb1b-") as temp:
            directory = Path(temp).resolve()
            normalized = inputs(directory)
            self.assertEqual(jobs.read_inputs(directory), (normalized, ALLOWED))
            (directory / "source.bin").write_bytes(b"not a build input")
            with self.assertRaises(BuilderError) as caught:
                jobs.read_inputs(directory)
            self.assertEqual(caught.exception.code, "job_invalid")
            (directory / "source.bin").unlink()
            (directory / "recipe.json").write_bytes(errors.json_bytes(recipe()))
            with self.assertRaises(BuilderError) as caught:
                jobs.read_inputs(directory)
            self.assertEqual(caught.exception.code, "schema_invalid")

    def test_font_digest_is_pinned_outside_job(self):
        with tempfile.TemporaryDirectory(prefix="mb1b-") as temp:
            directory = Path(temp).resolve()
            inputs(directory)
            font = directory / "fonts/Aileron-Regular-subset.ttf"
            data = bytearray(font.read_bytes())
            data[-1] ^= 1
            font.write_bytes(data)
            with self.assertRaises(BuilderError) as caught:
                jobs.read_inputs(directory)
            self.assertEqual(caught.exception.code, "font_missing")
            # Replacing both job copies cannot replace the installed trust anchor.
            manifest_path = directory / "fonts/fonts.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest["regular"]["sha256"] = sha256(data).hexdigest()
            manifest_path.write_bytes(errors.json_bytes(manifest))
            with self.assertRaises(BuilderError):
                jobs.read_inputs(directory)

    def test_include_directory_cannot_smuggle_a_file(self):
        with tempfile.TemporaryDirectory(prefix="mb1b-") as temp:
            directory = Path(temp).resolve()
            inputs(directory)
            (directory / "includes/0.glb").write_bytes(b"not yet supported")
            with self.assertRaises(BuilderError) as caught:
                jobs.read_inputs(directory)
            self.assertEqual(caught.exception.code, "composition_unavailable")
            self.assertEqual(caught.exception.path, "$.includes")

    def test_symlinks_are_not_read(self):
        with tempfile.TemporaryDirectory(prefix="mb1b-") as temp:
            parent = Path(temp).resolve()
            job = parent / "job"
            job.mkdir()
            inputs(job)
            source = parent / "foreign.txt"
            source.write_bytes(b"not an allowed file")
            (job / "allowed.json").unlink()
            try:
                (job / "allowed.json").symlink_to(source)
            except OSError:
                self.skipTest("This host does not permit creating symlinks")
            with self.assertRaises((BuilderError, ImportErrorType)):
                jobs.read_inputs(job)

    def test_result_round_trip_and_scalar_integrity(self):
        raw, value = sample()
        self.assertEqual(protocol.validate_result(value, raw, ALLOWED), value)
        for key, changed in (("schemaVersion", True), ("kind", "import"), ("triangles", 60001),
                             ("shift", [0,float("inf"),0]), ("outputBytes", 30*1024*1024+1),
                             ("recipeSha256", "b"*64), ("allowedSha256", "b"*64), ("outputSha256", "../file")):
            with self.subTest(key=key), self.assertRaises(ImportErrorType):
                protocol.validate_result({**deepcopy(value), key: changed}, raw, ALLOWED)
        for section in ("budgets", "provenance"):
            bad = deepcopy(value)
            bad[section]["triangles" if section == "budgets" else "hangHeight"] = True
            with self.assertRaises(ImportErrorType):
                protocol.validate_result(bad, raw, ALLOWED)

    def test_result_map_parts_materials_and_hang_height_are_bound(self):
        raw, value = sample()
        alterations = [
            lambda v: v["partMap"]["instances"].update({"body[1]": ["p:housing#0"]}),
            lambda v: v["partMap"]["entries"].update({"missing": ["p:housing#0"]}),
            lambda v: v["parts"][0].update(triangles=11),
            lambda v: v["parts"][0].update(key="p:other#0"),
            lambda v: v["materials"][0].update(defaultFinish={"appearanceId": "unlisted"}),
            lambda v: v["catalogDimensions"].update(height=2),
            lambda v: v["provenance"]["sitePrivate"].update(references=["rf-"+"a"*24]),
            lambda v: v["footprint"][0].reverse(),
            lambda v: v["lints"].append({"code": "unknown", "entryIds": [], "instances": []}),
            lambda v: v["warnings"].append("x"*301),
        ]
        for alter in alterations:
            bad = deepcopy(value)
            alter(bad)
            with self.assertRaises(ImportErrorType):
                protocol.validate_result(bad, raw, ALLOWED)

    def test_result_file_limits_hash_and_missing_completion_marker(self):
        raw, value = sample()
        with tempfile.TemporaryDirectory(prefix="mb1b-") as temp:
            job = Path(temp).resolve()
            payload = b"hash binding fixture"
            (job / "model.glb").write_bytes(payload)
            value.update(outputBytes=len(payload), outputSha256=sha256(payload).hexdigest())
            with self.assertRaises(ImportErrorType):
                protocol.read_result(job, raw, ALLOWED)
            (job / "result.json").write_bytes(errors.json_bytes(value))
            self.assertEqual(protocol.read_result(job, raw, ALLOWED), (value, payload))
            (job / "model.glb").write_bytes(b"changed")
            with self.assertRaises(ImportErrorType):
                protocol.read_result(job, raw, ALLOWED)
            with (job / "result.json").open("wb") as stream:
                stream.truncate(protocol.RESULT_BYTES+1)
            with self.assertRaises(ImportErrorType):
                protocol.read_result(job, raw, ALLOWED)

    def test_allowed_lists_are_closed_and_bounded(self):
        for value in ({}, {**ALLOWED, "extra": True}, {"categories": [], "appearanceIds": []},
                      {"categories": ["Material Handling"]*513, "appearanceIds": []},
                      {"categories": ["a"], "appearanceIds": ["x"]*2}):
            with self.assertRaises(BuilderError):
                jobs.validate_allowed(value)

    def test_footprint_allows_float32_rounding_but_not_unbounded_growth(self):
        raw, value = sample()
        value["footprint"][0][1]["x"] += 2e-8
        protocol.validate_result(value, raw, ALLOWED)
        value["footprint"][0][1]["x"] += .001
        with self.assertRaises(ImportErrorType):
            protocol.validate_result(value, raw, ALLOWED)

    def test_glb_metadata_is_bound_to_result_parts_and_materials(self):
        raw, value = sample()
        material = value["materials"][0]
        document = {
            "asset": {"generator": "model-builder-1"}, "scene": 0, "scenes": [{"nodes": [0]}],
            "nodes": [{"name": "housing", "mesh": 0}],
            "meshes": [{"name": "housing", "primitives": [{"indices": 0, "material": 0, "mode": 4}]}],
            "accessors": [{"type": "SCALAR", "count": 36}],
            "materials": [{"name": "housing (paint)", "extras": {
                "facilityAuthoredFinish": True, "facilityMaterialRole": "housing"},
                "pbrMetallicRoughness": {"baseColorFactor": material["baseColor"], "roughnessFactor": .6,
                                       "metallicFactor": 0},
                "alphaMode": "OPAQUE", "alphaCutoff": .5, "doubleSided": False, "emissiveFactor": [0,0,0]}]}
        protocol.validate_glb_metadata(document, value)
        for edit in (
                lambda d: d["nodes"][0].update(name="other"),
                lambda d: d["accessors"][0].update(count=33),
                lambda d: d["materials"][0]["extras"].update(facilityDefaultFinish="unlisted"),
                lambda d: d["materials"][0]["pbrMetallicRoughness"].update(roughnessFactor=.1)):
            changed = deepcopy(document)
            edit(changed)
            with self.assertRaises(ImportErrorType):
                protocol.validate_glb_metadata(changed, value)


if __name__ == "__main__":
    unittest.main()
