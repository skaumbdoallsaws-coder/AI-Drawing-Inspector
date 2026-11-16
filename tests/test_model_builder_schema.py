"""Dependency-free tests; also runnable with unittest when pytest is unavailable."""
from copy import deepcopy
from hashlib import sha256
import json
import struct
import unittest

from tests.model_builder_test_support import PACKAGE, REFERENCE, include, module, recipe, reference, shape

normalizer = module("recipe")
budgets = module("budgets")
Error = module("errors").ModelBuildError


class RecipeTests(unittest.TestCase):
    def refused(self, value, code="schema_invalid", path=None, **kwargs):
        with self.assertRaises(Error) as caught:
            normalizer.normalize_recipe(value, **kwargs)
        self.assertEqual(caught.exception.code, code)
        if path:
            self.assertEqual(caught.exception.path, path)
        self.assertLess(len(json.dumps(caught.exception.to_dict())), 1500)
        return caught.exception

    def test_defaults_round_trip_and_input_immutability(self):
        raw = recipe()
        before = deepcopy(raw)
        normalized = normalizer.normalize_recipe(raw, allowed_categories=["Material Handling"])
        self.assertEqual(raw, before)
        self.assertEqual(normalized, normalizer.normalize_recipe(normalized))
        self.assertEqual(normalized["materials"]["paint"],
                         dict(color="#52708a", roughness=.6, metalness=0, opacity=1, lit=0))
        self.assertEqual(normalized["entries"][0]["rotate"], dict(x=0, y=0, z=0))
        self.assertEqual(normalized["hangHeight"], 0)

    def test_all_reference_recipes_validate_and_fit_real_request_cap(self):
        for name in ("baler-vertical-42", "gaylord-on-pallet", "pack-station-printer",
                     "carrier-tag-ups", "pallet-plain", "roll-cage-plain"):
            with self.subTest(name=name):
                value = normalizer.normalize_recipe(reference(name))
                self.assertEqual(normalizer.normalize_recipe(value), value)
                self.assertLessEqual(len(normalizer.json_bytes({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "build_model_asset", "arguments": {"recipe": value}}})), 32 * 1024)
                self.assertLessEqual(budgets.estimate(value)["triangles"], 60000)

    def test_example_template_after_host_pins(self):
        value = reference("roll-cage-tag.template")
        entry = value["entries"][0]
        entry.update({k: include()[k] for k in ("include", "revision", "artifactSha256")})
        entry["recolor"][0]["select"] = "p:cage%20top%20rail#0"
        self.assertEqual(normalizer.normalize_recipe(value)["entries"][0]["id"], "cage")

    def test_closed_fields_finite_values_and_exact_discriminators(self):
        variants = [
            recipe(path="anywhere"), recipe(shape(command="anything")),
            recipe({**shape(), "group": [shape(id="child")]}),
            recipe({k: v for k, v in shape().items() if k != "shape"}),
            recipe(shape(rotate={"w": 1})), recipe(hangHeight=True), recipe(hangHeight=float("nan")),
            recipe(shape(max=[float("inf"), 1, 1])), recipe(name="\ud800"),
            recipe(shape(repeat={"count": True, "step": [0, 0, 0]})),
            recipe(shape(bendRadius=.1)), recipe(shape("lathe", degrees=180)),
            recipe(shape("tube", path=[[0, 0, 0], [0, 0, 0]])),
            recipe(shape("box", min=[1, 0, 0], max=[0, 1, 1])),
            recipe(shape("box", center=[0, 0, 0], size=[1, 1, 1])),
            recipe(shape("cylinder", to=[0, 0, 0])),
            recipe(shape("cylinder", radiusTo=.1, hollow=.1)),
            recipe(shape("torus", tubeRadius=.5)), recipe(shape("sphere", radii=[0, 1, 1])),
            recipe(shape("extrude", profile=[[0, 0], [1, 1], [0, 1], [1, 0]])),
            recipe(shape("extrude", profile=[[0, 0], [0, 0], [1, 1]])),
            recipe(shape("lathe", profile=[[-1, 0], [1, 1]])),
            recipe(front=["missing"]), recipe(surfaces=[
                {"id": "deck", "label": "deck", "height": 1, "rect": [0, 0, 0, 1]}]),
            recipe(shape(repeat={"count": 2, "step": [1, 0, 0]}, mirror={"plane": "x"})),
        ]
        for value in variants:
            with self.subTest(value=value):
                self.refused(value)

    def test_ids_depth_and_catalog_lists(self):
        self.refused(recipe(shape(), {"id": "assembly", "group": [shape()]}),
                     path="$.entries[1].group[0].id")
        self.refused(recipe(), allowed_categories=["other"])
        value = recipe(materials={"paint": {"color": "#AABBCC", "finish":
                       {"appearanceId": "Brushed steel", "color": "#ABCDEF", "roughness": .3, "metalness": .8}}})
        self.refused(value)
        normalized = normalizer.normalize_recipe(value, allowed_appearance_ids=["Brushed steel"])
        self.assertEqual(normalized["materials"]["paint"]["finish"]["color"], "#abcdef")
        for field, bad in (("roughness", 2), ("metalness", True), ("color", "blue")):
            broken = deepcopy(value)
            broken["materials"]["paint"]["finish"][field] = bad
            self.refused(broken, allowed_appearance_ids=["Brushed steel"])
        child = shape()
        for depth in range(4):
            child = {"id": "group-" + str(depth), "group": [child]}
        self.refused(recipe(child), "budget_exceeded")

    def test_include_schema_pins_selectors_and_ancestor_pattern(self):
        normalized = normalizer.normalize_recipe(recipe(include(recolor=[
            {"select": "p:rail~1#0", "material": "paint"},
            {"select": {"material": "steel"}, "material": "paint"},
            {"select": {"all": True}, "material": "paint"}])))
        self.assertEqual(normalized["entries"][0]["rotateY"], 0)
        for field in ("revision", "artifactSha256"):
            value = recipe(include())
            value["entries"][0].pop(field)
            self.refused(value)
        self.refused(recipe(include(repeat={"count": 2, "step": [1, 0, 0]})))
        self.refused(recipe(include(recolor=[{"select": {"all": True, "node": "x"}, "material": "paint"}])))
        value = recipe({"id": "assembly", "group": [include()], "mirror": {"plane": "x"}})
        self.assertEqual(budgets.estimate(normalizer.normalize_recipe(value))["includes"], 2)

    def test_print_forms_and_covered_glyphs(self):
        items = [{"text": "OUTBOUND\nA1", "box": [0, 0, 1, 1], "color": "#ffffff"},
                 {"rect": [0, 0, 1, 1], "fill": "#ffffff"},
                 {"line": [0, 0, 1, 1], "color": "#ffffff", "lineMm": 1},
                 {"circle": [.5, .5, .2], "stroke": "#ffffff"},
                 {"barcode": [0, 0, 1, 1], "seed": 12},
                 {"stripes": [0, 0, 1, 1], "colors": ["#ffffff", "#000000"], "angleDegrees": 45, "widthMm": 2},
                 {"dots": {"area": [0, 0, 1, 1], "pitchMm": 10, "radiusMm": 2, "color": "#ffffff"}}]
        value = normalizer.normalize_recipe(recipe(shape("panel", print={"background": "#000000", "items": items})))
        self.assertEqual(value["entries"][0]["print"]["items"][0]["align"], "center")
        for invalid in ({}, {**items[0], "rect": [0, 0, 1, 1]}, {**items[0], "text": "x" * 61}):
            self.refused(recipe(shape("panel", print={"background": "#000000", "items": [invalid]})))
        for invalid in ({**items[0], "text": "\u00e9"}, {**items[0], "text": "a\nb\nc\nd"},
                        {"rect": [0, 0, 1, 1]}):
            self.refused(recipe(shape("panel", print={"background": "#000000", "items": [invalid]})), "print_invalid")
        self.refused(recipe(shape("panel"), materials={"paint": {"color": "#ffffff",
                     "finish": {"appearanceId": "steel"}}}), "print_invalid", allowed_appearance_ids=["steel"])

    def test_pinned_font_sha_and_cmap(self):
        manifest = json.loads((PACKAGE / "fonts/fonts.json").read_text())
        font = (PACKAGE / "fonts" / manifest["regular"]["file"]).read_bytes()
        self.assertEqual(len(font), 12676)
        self.assertEqual(sha256(font).hexdigest(),
                         "69853909b940023570964e29cffe30da95aea8de3627736b5cd15ab30143169f")
        tables = {font[p:p+4]: struct.unpack_from(">II", font, p+8)
                  for p in range(12, 12+16*struct.unpack_from(">H", font, 4)[0], 16)}
        start, _ = tables[b"cmap"]
        cmap = set()
        for p in range(start+4, start+4+8*struct.unpack_from(">H", font, start+2)[0], 8):
            offset = start+struct.unpack_from(">I", font, p+4)[0]
            if struct.unpack_from(">H", font, offset)[0] != 4:
                continue
            count = struct.unpack_from(">H", font, offset+6)[0] // 2
            end_pos, start_pos = offset+14, offset+16+2*count
            delta_pos, range_pos = start_pos+2*count, start_pos+4*count
            for i in range(count):
                lo, hi = struct.unpack_from(">H", font, start_pos+2*i)[0], struct.unpack_from(">H", font, end_pos+2*i)[0]
                delta, advance = struct.unpack_from(">h", font, delta_pos+2*i)[0], struct.unpack_from(">H", font, range_pos+2*i)[0]
                for char in range(lo, min(hi+1, 65535)):
                    glyph = struct.unpack_from(">H", font, range_pos+2*i+advance+2*(char-lo))[0] if advance else char
                    if glyph and (glyph+delta) % 65536:
                        cmap.add(char)
        self.assertEqual(cmap | {10}, normalizer.PRINT_CODEPOINTS)

    def test_sources_and_references_are_separated_before_publication(self):
        value = normalizer.normalize_recipe(recipe(references=["rf-" + "a" * 24], sizeBasis={
            "kind": "research", "note": "Generic dimensions", "sources": [
                {"url": "https://example.invalid/equipment", "title": "Equipment dimensions"}]}))
        portable, private = normalizer.portable_recipe(value)
        self.assertNotIn("references", portable)
        self.assertNotIn("sources", portable["sizeBasis"])
        self.assertEqual(private["references"], value["references"])
        self.assertEqual(len(private["sources"]), 1)
        value["sizeBasis"]["sources"][0]["url"] = "https://user:password@example.invalid/"
        self.refused(value)

    def test_schema_caps(self):
        variants = [
            recipe(shape("cylinder", segments=65)), recipe(shape("tube", sides=25)),
            recipe(shape("tube", path=[[0, i/100, 0] for i in range(65)])),
            recipe(shape("lathe", segments=65)), recipe(shape("torus", segments=65)),
            recipe(shape("extrude", profile=[[i/100, 0] for i in range(65)])),
            recipe(shape(repeat={"count": 201, "step": [0, 0, 0]})),
            recipe(shape(around={"count": 121, "axis": "y", "center": [0, 0, 0]})),
            recipe(shape(scatter={"count": 61, "seed": 0, "within": {"min": [-1]*3, "max": [1]*3}})),
            recipe(shape(scatter={"count": 1, "seed": 0, "within": {"min": [-1]*3, "max": [1]*3},
                                  "sizeJitter": [.31, 0, 0]})),
            recipe(shape(min=[-15.1, 0, 0])), recipe(hangHeight=3.001),
            recipe(materials={f"m{i}": {"color": "#123456"} for i in range(33)}),
            recipe(*[shape(id=f"entry-{i}") for i in range(161)]),
            recipe(shape("panel", print={"background": "#ffffff", "items": [
                {"barcode": [0, 0, 1, 1], "seed": i} for i in range(25)]})),
            recipe(tags=["a"]*9), recipe(references=["rf-"+"a"*24]*4),
            recipe(description="x"*301),
        ]
        for value in variants:
            with self.subTest(value=value):
                self.refused(value)

    def test_preflight_pattern_and_geometry_budgets(self):
        self.refused(recipe(shape(grid={"count": [21, 20], "step1": [0, 0, 0], "step2": [0, 0, 0]})),
                     "budget_exceeded")
        nested = {"id": "assembly", "repeat": {"count": 16, "step": [0, 0, 0]}, "group": [
            shape(repeat={"count": 200, "step": [0, 0, 0]})]}
        self.refused(recipe(nested), "budget_exceeded")
        self.refused(recipe(shape("sphere", repeat={"count": 114, "step": [0, 0, 0]})), "budget_exceeded")
        self.refused(recipe(*[shape(id=f"piece-{i}", name=f"piece {i}") for i in range(65)]), "budget_exceeded")
        self.refused(recipe(shape("panel", repeat={"count": 9, "step": [0, 0, 0]})), "budget_exceeded")
        self.refused(recipe(shape("panel", repeat={"count": 4, "step": [0, 0, 0]})), "budget_exceeded")
        # 400 descendants in addition to their groups.
        self.refused(recipe(*[{"id": f"assembly-{g}", "group": [shape(id=f"p-{g}-{i}") for i in range(100)]}
                              for g in range(4)]), "budget_exceeded")
        # Raw size cap is tested separately from the structural limits.
        value = recipe(description="x" * 24576)
        self.refused(value, "budget_exceeded", "$")

    def test_future_include_aggregate_budgets_without_geometry(self):
        self.refused(recipe(*[include(id=f"i-{i}") for i in range(4)]), "budget_exceeded")
        value = normalizer.normalize_recipe(recipe(include()))
        valid = dict(bytes=1, texturePixels=0, triangles=12, primitives=1, materials=1)
        for key, excessive in (("bytes", 8*1024*1024+1), ("texturePixels", 16000001),
                               ("triangles", 60001), ("primitives", 401), ("materials", 65)):
            with self.subTest(key=key), self.assertRaises(Error) as caught:
                budgets.estimate(value, include_stats={"host": {**valid, key: excessive}})
            self.assertEqual(caught.exception.code, "budget_exceeded")
        value = normalizer.normalize_recipe(recipe(*[include(id=f"i-{i}") for i in range(3)]))
        with self.assertRaises(Error):
            budgets.estimate(value, include_stats={f"i-{i}": {**valid, "bytes": 6*1024*1024} for i in range(3)})


if __name__ == "__main__":
    unittest.main()
