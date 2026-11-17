"""Small stdlib-only checks for MB2; no renderer or subprocess imports."""
from copy import deepcopy
from hashlib import sha256
import struct
import unittest
import zlib

from tests.model_builder_test_support import include, module, recipe, shape

contract, budgets = module("print_contract"), module("budgets")
normalize = module("recipe").normalize_recipe
Error = module("errors").ModelBuildError


def png(width=64, height=32, *, pixels=None, extra=b""):
    def chunk(kind, value):
        return struct.pack(">I", len(value))+kind+value+struct.pack(">I", zlib.crc32(kind+value) & 0xffffffff)
    pixels = b"\0"*(height*(1+3*width)) if pixels is None else pixels
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + extra + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def textured_metadata():
    """A wire fixture, not a substitute for actual renderer/geometry verification."""
    from tests.test_model_builder_protocol import sample
    protocol = module("protocol")
    raw = normalize(recipe(shape("panel", size=[.2, .1], back="#333333"),
        size={"width": .2, "height": .1, "depth": .0025}, materials={"paint": {"color": "#333333", "lit": .5}}))
    _, value = sample()
    value.update(recipeSha256=protocol.digest(raw), dimensions=dict(raw["size"]), catalogDimensions=dict(raw["size"]),
                 triangles=14, budgets=budgets.estimate(raw), provenance=protocol.provenance(raw))
    back = dict(value["materials"][0], name="back:paint:#333333")
    texture = {"image": 0, "wrapS": 33071, "wrapT": 33071}
    front = dict(back, name="print:body", artwork=True, texture=texture, emissiveTexture=texture,
                 baseColor=[1, 1, 1, 1], emissive=[.5, .5, .5])
    value["materials"] = [back, front]
    value["parts"] = [{"key": f"p:housing#{i}", "name": "housing", "material": i, "triangles": n}
                      for i, n in enumerate((12, 2))]
    keys = [p["key"] for p in value["parts"]]
    value["partMap"] = {"entries": {"body": keys}, "instances": {"body[0]": keys}}
    value["footprint"] = [[{"x": x, "z": z} for x, z in ((-.1, -.00125), (.1, -.00125), (.1, .00125), (-.1, .00125))]]
    data = png(500, 250)
    value["images"] = [{"entryId": "body", "width": 500, "height": 250, "mimeType": "image/png",
                        "bytes": len(data), "sha256": sha256(data).hexdigest()}]
    document = {"asset": {"generator": "model-builder-1"}, "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "housing", "mesh": 0}], "meshes": [{"name": "housing", "primitives": [
            {"indices": 0, "material": 0, "mode": 4},
            {"indices": 1, "material": 1, "mode": 4, "attributes": {"TEXCOORD_0": 2}}]}],
        "accessors": [{"type": "SCALAR", "count": 36}, {"type": "SCALAR", "count": 6}],
        "images": [{"bufferView": 0, "mimeType": "image/png"}], "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{"wrapS": 33071, "wrapT": 33071, "magFilter": 9729, "minFilter": 9987}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(data)}], "materials": []}
    for material in (back, front):
        pbr = {"baseColorFactor": material["baseColor"], "roughnessFactor": .6, "metallicFactor": 0}
        item = {"name": f"housing ({material['name']})", "pbrMetallicRoughness": pbr,
                "alphaMode": "OPAQUE", "alphaCutoff": .5, "doubleSided": False,
                "emissiveFactor": material["emissive"],
                "extras": {"facilityAuthoredFinish": True, "facilityMaterialRole": "housing"}}
        if material.get("artwork"):
            item["extras"]["facilityArtwork"] = True
            pbr["baseColorTexture"] = item["emissiveTexture"] = {"index": 0, "texCoord": 0}
        document["materials"].append(item)
    encoded = module("errors").json_bytes(document)
    encoded += b" "*(-len(encoded) % 4)
    binary = data+b"\0"*(-len(data) % 4)
    payload = (struct.pack("<4sII", b"glTF", 2, 28+len(encoded)+len(binary))
               + struct.pack("<I4s", len(encoded), b"JSON")+encoded
               + struct.pack("<I4s", len(binary), b"BIN\0")+binary)
    value.update(outputBytes=len(payload), outputSha256=sha256(payload).hexdigest())
    return raw, value, document, payload


class PrintContractTests(unittest.TestCase):
    def test_textured_result_and_glb_metadata_bind_the_image(self):
        from tests.test_model_builder_protocol import ALLOWED, ImportErrorType
        protocol = module("protocol")
        raw, value, document, payload = textured_metadata()
        protocol.validate_result(value, raw, ALLOWED)
        protocol.validate_glb_metadata(document, value, payload=payload)
        for edit in (lambda v: v["images"][0].update(sha256="b"*64),
                     lambda v: v["materials"][1].update(emissiveTexture=None)):
            changed = deepcopy(value)
            edit(changed)
            with self.assertRaises(ImportErrorType):
                protocol.validate_glb_metadata(document, changed, payload=payload)
        changed = deepcopy(document)
        changed["meshes"][0]["primitives"][1]["attributes"] = {}
        with self.assertRaises(ImportErrorType):
            protocol.validate_glb_metadata(changed, value, payload=payload)

    def test_print_result_rejects_unbudgeted_images_tinted_artwork_and_finishes(self):
        from tests.test_model_builder_protocol import ALLOWED, ImportErrorType
        protocol = module("protocol")
        raw, value, _, _ = textured_metadata()
        for edit in (lambda v: v["images"][0].update(width=1025),
                     lambda v: v["images"][0].update(entryId="unlisted"),
                     lambda v: v["materials"][1].update(baseColor=[.3, .2, .1, 1]),
                     lambda v: v["materials"][1].update(defaultFinish={"appearanceId": "steel"})):
            changed = deepcopy(value)
            allowed = dict(ALLOWED, appearanceIds=["steel"])
            changed["allowedSha256"] = protocol.digest(allowed)
            edit(changed)
            with self.assertRaises(ImportErrorType):
                protocol.validate_result(changed, raw, allowed)

    def test_png_is_metadata_free_and_decoded_size_is_bounded(self):
        self.assertEqual(contract.png_dimensions(png()), (64, 32))
        bad_crc = bytearray(png())
        bad_crc[-1] ^= 1
        for payload in (b"bad", bytes(bad_crc), png()[:-1], png()+b"trailing", png(width=1025),
                        png(width=0), png(1, 1), png(pixels=b"\0"*100000), png(pixels=b"\0"*10),
                        png(pixels=b"\x05"*(32*193)), png(extra=struct.pack(">I4sI", 0, b"tEXt", 0))):
            with self.subTest(size=len(payload)), self.assertRaises(ValueError):
                contract.png_dimensions(payload)

    def test_print_size_uses_panel_aspect_and_a_capped_common_scale(self):
        for size, expected in (([.36, .2], (900, 500)), ([.02, .01], (64, 32)),
                               ([1, .5], (1024, 512)), ([.1, .2], (250, 500)),
                               ([.0005, 30], (1, 1024))):
            self.assertEqual(budgets.panel_pixels({"size": size}), expected)

    def test_eight_panels_and_four_megapixels_are_preflight_limits(self):
        entry = shape("panel", size=[.4, .2], repeat={"count": 8, "step": [0, 0, 0]})
        self.assertEqual(budgets.estimate(normalize(recipe(entry)))["printPixels"], 4_000_000)
        for changes in ({"repeat": {"count": 9, "step": [0, 0, 0]}}, {"size": [.4, .201]}):
            with self.assertRaises(Error) as caught:
                normalize(recipe({**entry, **changes}))
            self.assertEqual(caught.exception.code, "budget_exceeded")

    def test_total_texture_budget_already_reserves_prints_for_mb3(self):
        entry = shape("panel", size=[.4, .2], repeat={"count": 8, "step": [0, 0, 0]})
        value = normalize(recipe(entry, include()))
        statistics = {"bytes": 100, "texturePixels": 12_000_000, "triangles": 12,
                      "primitives": 1, "materials": 1}
        self.assertEqual(budgets.estimate(value, include_stats={"host": statistics})["texturePixels"], 16_000_000)
        with self.assertRaises(Error) as caught:
            budgets.estimate(value, include_stats={"host": {**statistics, "texturePixels": 12_000_001}})
        self.assertEqual(caught.exception.code, "budget_exceeded")

    def test_coverage_refusal_names_the_character_and_path(self):
        with self.assertRaises(Error) as caught:
            normalize(recipe(shape("panel", print={"background": "#ffffff", "items": [
                {"text": "caf\u00e9", "box": [0, 0, 1, 1], "color": "#000000"}]})))
        self.assertEqual(caught.exception.code, "print_invalid")
        self.assertEqual(caught.exception.path, "$.entries[0].print.items[0].text")
        self.assertIn("\u00e9", caught.exception.problem)

    def test_bounded_overflow_can_be_linted_but_large_coordinates_refuse(self):
        item = {"rect": [-.1, -.2, 1.1, 1.2], "fill": "#123456"}
        normalize(recipe(shape("panel", print={"background": "#ffffff", "items": [item]})))
        self.assertTrue(contract.outside_panel(item, [.2, .1]))
        self.assertFalse(contract.outside_panel({"rect": [0, 0, 1, 1]}, [.2, .1]))
        self.assertTrue(contract.outside_panel({"circle": [.5, .5, .3]}, [.2, .1]))
        self.assertTrue(contract.outside_panel({"line": [0, 0, 1, 1], "lineMm": 1}, [.2, .1]))
        for invalid in (-1.01, 2.01):
            broken = deepcopy(item)
            broken["rect"][0] = invalid
            with self.assertRaises(Error):
                normalize(recipe(shape("panel", print={"background": "#ffffff", "items": [broken]})))

    def test_barcode_stream_is_versioned_and_deterministic(self):
        a, b, c = (contract.BarcodeRandom(seed) for seed in (10482, 10482, 17))
        widths = [a.width() for _ in range(64)]
        self.assertEqual(widths, [b.width() for _ in range(64)])
        self.assertNotEqual(widths, [c.width() for _ in range(64)])
        self.assertEqual(set(widths), {1, 2, 3, 4})

    def test_package_and_job_fonts_have_identical_checked_bytes(self):
        from pathlib import Path
        import tempfile
        from tests.test_model_builder_protocol import inputs
        jobs = module("job_io")
        with tempfile.TemporaryDirectory(prefix="mb2-font-") as temp:
            job = Path(temp).resolve()
            inputs(job)
            self.assertEqual(jobs.font_bytes(), jobs.font_bytes(job / "fonts"))
            font = job / "fonts/Aileron-Regular-subset.ttf"
            font.write_bytes(b"invalid")
            with self.assertRaises(Error) as caught:
                jobs.font_bytes(job / "fonts")
            self.assertEqual(caught.exception.code, "font_missing")


if __name__ == "__main__":
    unittest.main()
