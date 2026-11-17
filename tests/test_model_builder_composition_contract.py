"""MB3 stdlib preflight tests. No numpy, Pillow, pytest or application imports."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import struct
import zlib

from tests.model_builder_test_support import include, module, recipe
from tests.model_builder_composition_support import contract, credit, edit_glb, triangle_glb

errors = module("errors")
normalize = module("recipe").normalize_recipe


def sources_for(raw, payload):
    item = raw["entries"][0]
    record = {"id": item["id"], "assetId": item["include"], "revision": item["revision"],
              "artifactSha256": sha256(payload).hexdigest(), "sourceToCanonical": contract.IDENTITY,
              "attribution": None, "hasSurfaces": False}
    item["artifactSha256"] = record["artifactSha256"]
    return {item["id"]: {"manifest": record, "payload": payload}}


class CompositionContractTests(unittest.TestCase):
    def test_keys_names_ordinals_and_long_path_fallback(self):
        payload = triangle_glb(copies=2, duplicate=True)
        info = contract.artifact_info(payload)
        self.assertEqual([p["key"] for p in info["parts"]], ["p:rail~0#0", "p:rail~1#0"])
        self.assertEqual([p["importKey"] for p in info["parts"]], ["p0", "p1"])
        self.assertEqual(info["stats"]["triangles"], 2)
        payload = edit_glb(payload, lambda d: d["nodes"][0].update(name="a/b %"))
        self.assertEqual(contract.artifact_info(payload)["parts"][0]["key"], "p:a%2Fb%20%25#0")
        payload = edit_glb(payload, lambda d: d["nodes"][0].update(name="x"*600))
        self.assertEqual(contract.artifact_info(payload)["parts"][0]["key"], "p:@0#0")

    def test_include_60001_refuses_before_geometry_or_images(self):
        raw = recipe(include())
        sources = sources_for(raw, triangle_glb(triangles=60001))
        with self.assertRaises(errors.ModelBuildError) as caught:
            contract.prepare_sources(normalize(raw), sources)
        self.assertEqual(caught.exception.code, "budget_exceeded")
        self.assertEqual(caught.exception.path, "$.entries[0]")
        self.assertEqual(caught.exception.triangles, 60001)

    def test_triangle_and_primitive_limits_count_group_copies_not_include_entries(self):
        for triangles, count in ((30001, 2), (1, 401)):
            raw = recipe(include())
            sources = sources_for(raw, triangle_glb(triangles=triangles))
            # Nested counts stay within each pattern's schema cap.
            leaf = raw["entries"][0]
            raw["entries"] = [{"id": "copies", "group": [leaf], "repeat": {"count": count if count < 400 else 200,
                                                                                 "step": [0, 0, 0]}}]
            if count > 400:
                raw["entries"] = [{"id": "outer", "group": raw["entries"], "repeat": {"count": 3, "step": [0, 0, 0]}}]
            with self.assertRaises(errors.ModelBuildError) as caught:
                contract.prepare_sources(normalize(raw), sources)
            self.assertEqual(caught.exception.code, "budget_exceeded")

    def test_copy_limit_budgets_and_byte_sizes(self):
        raw = recipe(include())
        sources = sources_for(raw, triangle_glb())
        leaf = raw["entries"][0]
        raw["entries"] = [{"id": "copies", "group": [leaf], "repeat": {"count": 4, "step": [0, 0, 0]}}]
        normalized = normalize(raw)
        prepared, _ = contract.prepare_sources(normalized, sources)
        stats = {key: value["info"]["stats"] for key, value in prepared.items()}
        budgets = module("budgets").estimate(normalized, include_stats=stats)
        self.assertEqual(budgets["includes"], 1)
        self.assertEqual(budgets["triangles"], 4)
        self.assertEqual(budgets["includeBytes"], len(sources["host"]["payload"]))

    def test_recolor_split_counts_output_materials_before_expansion(self):
        raw = recipe(include(recolor=[{"select": "p:rail~1#0", "material": "paint"}]))
        sources = sources_for(raw, triangle_glb(copies=2, duplicate=True))
        prepared, _ = contract.prepare_sources(normalize(raw), sources)
        self.assertEqual(prepared["host"]["info"]["stats"]["materials"], 2)

    def test_included_print_and_decoded_texture_budgets(self):
        value = normalize(recipe(include()))
        stats = {"bytes": 1, "triangles": 12, "primitives": 1, "materials": 1, "texturePixels": 4_000_000,
                 "printedPanels": 8, "printPixels": 4_000_000}
        budgets = module("budgets")
        self.assertEqual(budgets.estimate(value, include_stats={"host": stats})["texturePixels"], 4_000_000)
        for key, limit in (("printedPanels", 8), ("printPixels", 4_000_000), ("texturePixels", 16_000_000)):
            with self.assertRaises(errors.ModelBuildError) as caught:
                budgets.estimate(value, include_stats={"host": {**stats, key: limit+1}})
            self.assertEqual(caught.exception.code, "budget_exceeded")

    def test_included_png_allows_small_rgba_but_still_rejects_metadata_and_bad_crc(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data))+kind+data+struct.pack(">I", zlib.crc32(kind+data) & 0xffffffff)
        header = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0))
        tail = chunk(b"IDAT", zlib.compress(b"\0"+b"\x80"*8)) + chunk(b"IEND", b"")
        checker = module("print_contract").png_dimensions
        self.assertEqual(checker(header+tail, included=True), (2, 1))
        for payload in (header+chunk(b"tEXt", b"name\0value")+tail, header+tail[:-1]+b"x"):
            with self.assertRaises(ValueError):
                checker(payload, included=True)
        with self.assertRaises(ValueError):
            checker(header+tail)

    def test_hash_frame_and_second_credit_refusals(self):
        for mutation, code in (("hash", "include_mismatch"), ("frame", "include_invalid"), ("credit", "include_licence")):
            raw = recipe(include())
            sources = sources_for(raw, triangle_glb())
            if mutation == "hash":
                sources["host"]["payload"] += b"x"
            elif mutation == "frame":
                sources["host"]["manifest"]["sourceToCanonical"] = [0]*16
            else:
                sources["host"]["manifest"]["attribution"] = credit()
                other = deepcopy(raw["entries"][0])
                other["id"] = "second"
                raw["entries"].append(other)
                sources["second"] = deepcopy(sources["host"])
                sources["second"]["manifest"]["id"] = "second"
            with self.assertRaises(errors.ModelBuildError) as caught:
                contract.prepare_sources(normalize(raw), sources)
            self.assertEqual(caught.exception.code, code)

    def test_recolor_exact_keys_import_selectors_last_match_and_refusals(self):
        info = contract.artifact_info(triangle_glb(copies=2, duplicate=True))
        raw = normalize(recipe(include(recolor=[{"select": {"all": True}, "material": "paint"},
                                                 {"select": "p:rail~1#0", "material": "red"}]),
                               materials={"paint": {"color": "#aaaaaa"}, "red": {"color": "#ff0000"}}))
        entry = raw["entries"][0]
        self.assertEqual([p["replacement"] for p in contract.planned_parts(entry, info, "$.entries[0]")], ["paint", "red"])
        for selector in ({"part": "p1"}, {"node": "rail"}, {"mesh": "rail mesh"}, {"material": "steel"}):
            entry["recolor"] = [{"select": selector, "material": "paint"}]
            self.assertTrue(any(p["replacement"] for p in contract.planned_parts(entry, info, "$")))
        for selector, artwork in (("p:missing#0", False), ({"all": True}, True)):
            info["parts"][0]["artwork"] = artwork
            entry["recolor"] = [{"select": selector, "material": "paint"}]
            with self.assertRaises(errors.ModelBuildError) as caught:
                contract.planned_parts(entry, info, "$.entries[0]")
            self.assertEqual(caught.exception.code, "recolor_invalid")

    def test_copied_manifest_exact_names_and_hash(self):
        raw = recipe(include())
        sources = sources_for(raw, triangle_glb())
        raw = normalize(raw)
        with tempfile.TemporaryDirectory(prefix="mb3-contract-") as temp:
            job = Path(temp)
            folder = job / "includes"
            folder.mkdir()
            (folder / "0.glb").write_bytes(sources["host"]["payload"])
            (folder / "manifest.json").write_bytes(errors.json_bytes([sources["host"]["manifest"]]))
            self.assertEqual(contract.read_sources(job, raw), sources)
            (folder / "0.glb").write_bytes(b"changed")
            with self.assertRaises(errors.ModelBuildError) as caught:
                contract.read_sources(job, raw)
            self.assertEqual(caught.exception.code, "include_mismatch")

    def test_scalar_preflight_rejects_cycles_and_external_images(self):
        payload = triangle_glb()
        for edit in (lambda d: d["nodes"][0].update(children=[0]),
                     lambda d: d.update(images=[{"uri": "https://example.org/texture.png"}])):
            with self.assertRaises(errors.ModelBuildError) as caught:
                contract.artifact_info(edit_glb(payload, edit))
            self.assertEqual(caught.exception.code, "include_invalid")

    def test_result_protocol_binds_include_maps_frame_credit_and_budget(self):
        # Wire validation only; actual geometry and process parity have separate tests.
        from tests.test_model_builder_protocol import ALLOWED, ImportErrorType, sample
        protocol = module("protocol")
        raw = recipe(include())
        sources = sources_for(raw, triangle_glb())
        raw = normalize(raw)
        prepared, _ = contract.prepare_sources(raw, sources)
        _, value = sample()
        key = "p:host%3A%20rail-0#0"
        value.update(recipeSha256=protocol.digest(raw), provenance=protocol.provenance(raw), triangles=1,
                     budgets=module("budgets").estimate(raw, include_stats={"host": prepared["host"]["info"]["stats"]}),
                     parts=[{"key": key, "name": "host: rail-0", "material": 0, "triangles": 1}],
                     partMap={"entries": {"host": [key]}, "instances": {"host[0]": [key]}})
        value["materials"][0]["name"] = "include:host:0"
        entry = raw["entries"][0]
        value["includes"] = [{"includeId": "host", "assetId": entry["include"], "revision": entry["revision"],
                              "artifactSha256": entry["artifactSha256"], "anchorable": True,
                              "frame": {"yaw": 0, "translation": [0, 0, 0]}, "partMap": {"p:rail-0#0": key}}]
        protocol.validate_result(value, raw, ALLOWED, include_sources=sources)
        for edit in (lambda v: v["includes"][0].update(partMap={}),
                     lambda v: v["includes"][0]["frame"].update(yaw=45),
                     lambda v: v.update(attribution=credit()),
                     lambda v: v["budgets"].update(primitives=2)):
            changed = deepcopy(value)
            edit(changed)
            with self.assertRaises(ImportErrorType):
                protocol.validate_result(changed, raw, ALLOWED, include_sources=sources)


if __name__ == "__main__":
    unittest.main()
