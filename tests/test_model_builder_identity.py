"""MB4a portable identities and persisted include metadata, stdlib only."""
from copy import deepcopy
from hashlib import sha256
import unittest

from tests.model_builder_test_support import module, recipe, include, gltf
from tests.model_builder_composition_support import triangle_glb

identity = module("identity")
drafts = module("drafts")
normalize = module("recipe").normalize_recipe


def draft(raw=None, **changes):
    raw = normalize(raw or recipe())
    result = {"outputSha256": "f"*64, "dimensions": {"width": 1, "height": 1, "depth": 1},
              "catalogDimensions": {"width": 1, "height": 1+raw["hangHeight"], "depth": 1},
              "triangles": 12, "includes": [], "attribution": None, "surfaces": [],
              "footprint": [[{"x": -.5, "z": -.5}, {"x": .5, "z": -.5},
                             {"x": .5, "z": .5}, {"x": -.5, "z": .5}]], **changes}
    return drafts.make_draft(raw, result, "a"*24, 1700000000)


class IdentityTests(unittest.TestCase):
    def test_canonical_identity_and_bounded_slug(self):
        value = draft(recipe(name="Generic "+"equipment "*6))
        ident = identity.asset_identity(value)
        self.assertEqual(ident, identity.asset_identity(deepcopy(value)))
        self.assertRegex(ident["assetId"], r"^asset-built-[a-z0-9-]{1,40}-[0-9a-f]{24}$")
        self.assertEqual(ident["sha256"], sha256(module("errors").json_bytes(ident["identity"])).hexdigest())
        self.assertEqual(value["draftId"], "md-"+ident["sha256"][:24])
        self.assertEqual(set(ident["identity"]), {"engine", "recipe", "includes", "model", "entry"})
        self.assertNotIn("source", ident["identity"]["entry"])

    def test_draft_times_scope_and_references_do_not_change_identity(self):
        a = draft(recipe(references=["rf-"+"1"*24]))
        b = draft(recipe(references=["rf-"+"2"*24]))
        b.update(scope="b"*24, created=b["created"]+10, expires=b["expires"]+10)
        self.assertEqual(identity.asset_identity(a), identity.asset_identity(b))
        self.assertNotIn("references", repr(identity.asset_identity(a)))
        self.assertNotEqual(a["recipe"], b["recipe"])

    def test_sources_are_portable_provenance_and_change_the_complete_identity(self):
        a = draft()
        b = draft(recipe(sizeBasis={"kind": "research", "note": "Generic dimensions",
                                     "sources": [{"url": "https://example.org/spec", "title": "Dimensions"}]}))
        portable, metadata = module("recipe").portable_recipe(b["recipe"])
        self.assertNotIn("sources", portable["sizeBasis"])
        self.assertEqual(b["buildProvenance"]["sources"], metadata["sources"])
        self.assertEqual(b["buildProvenance"]["recipeSha256"], sha256(module("errors").json_bytes(portable)).hexdigest())
        self.assertNotEqual(a["assetId"], b["assetId"])
        c = deepcopy(b)
        c["buildProvenance"]["sources"][0]["title"] = "Revised dimensions"
        self.assertNotEqual(identity.asset_identity(b), identity.asset_identity(c))

    def test_each_size_basis_matches_the_recipe_schema(self):
        for kind in ("user", "layout", "document", "photo", "research", "typical"):
            with self.subTest(kind=kind):
                value = draft(recipe(sizeBasis={"kind": kind, "note": ""}))
                self.assertEqual(identity.validate_provenance(value["buildProvenance"])["sizeBasis"]["kind"], kind)

    def test_complete_identity_changes_for_model_recipe_and_catalog_semantics(self):
        original = draft()
        for key, value in (("outputSha256", "e"*64), ("footprint", []), ("surfaces", [{"label": "top"}])):
            changed = deepcopy(original)
            changed[key] = value
            self.assertNotEqual(identity.asset_identity(original), identity.asset_identity(changed))
        changed = deepcopy(original)
        changed["recipe"]["description"] = "New generic description"
        self.assertNotEqual(identity.asset_identity(original), identity.asset_identity(changed))

    def test_derived_from_is_validated_and_identity_bound(self):
        value = draft()
        changed = deepcopy(value)
        changed["buildProvenance"] = identity.build_provenance(value["recipe"], 12, "asset-example")
        self.assertNotEqual(identity.asset_identity(value), identity.asset_identity(changed))
        for bad in ("../outside", "", 5):
            with self.assertRaises(ValueError):
                identity.build_provenance(value["recipe"], 12, bad)

    def test_provenance_rejects_unknown_fields_nonfinite_and_credentials(self):
        base = draft()["buildProvenance"]
        for fields in ({"triangles": True}, {"triangles": 60001}, {"triangles": float("nan")},
                       {"generator": "unknown"}, {"extra": "no"}, {"recipeSha256": "x"},
                       {"sizeBasis": {"kind": "measured", "note": ""}},
                       {"sources": [{"url": "https://user:password@example.org/spec", "title": "Spec"}]},
                       {"sources": [{"url": "https://example.org:99999/spec", "title": "Spec"}]},
                       {"sources": [{"url": "https://example.org/a b", "title": "Spec"}]}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                identity.validate_provenance({**base, **fields})

    def test_draft_validation_is_strict_and_supports_hang_height(self):
        value = draft(recipe(hangHeight=1.2))
        self.assertEqual(value["catalogDimensions"]["height"], 2.2)
        self.assertEqual(drafts.validate_draft(value), value)
        for key, bad in (("schemaVersion", True), ("kind", "import"), ("scope", "../outside"),
                         ("expires", value["created"]+1), ("draftId", "md-"+"0"*24),
                         ("catalogDimensions", value["dimensions"])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                drafts.validate_draft({**value, key: bad})

    def test_include_frames_and_maps_are_bound_to_output_bytes(self):
        raw = normalize(recipe(include()))
        entry = raw["entries"][0]
        record = {"includeId": entry["id"], "assetId": entry["include"], "revision": entry["revision"],
                  "artifactSha256": entry["artifactSha256"], "anchorable": True,
                  "frame": {"yaw": 30, "translation": [0, 0, 0]}, "partMap": {"p:source#0": "p:rail-0#0"}}
        payload = triangle_glb()
        bound = identity.bind_includes(payload, [record])
        self.assertEqual(bound, identity.bind_includes(payload, deepcopy([record])))
        self.assertNotEqual(bound, payload)
        identity.validate_includes([record], raw, gltf(bound))
        changed = deepcopy(record)
        changed["frame"]["translation"][0] = 1
        with self.assertRaises(ValueError):
            identity.validate_includes([changed], raw, gltf(bound))
        changed = deepcopy(record)
        changed["partMap"]["p:source#0"] = "p:missing#0"
        with self.assertRaises(ValueError):
            identity.validate_includes([changed], raw, gltf(identity.bind_includes(payload, [changed])))

    def test_non_anchorable_include_has_no_frame_and_no_includes_preserves_bytes(self):
        raw = normalize(recipe({"id": "group", "group": [include()], "rotate": {"x": 10}}))
        entry = raw["entries"][0]["group"][0]
        record = {"includeId": entry["id"], "assetId": entry["include"], "revision": entry["revision"],
                  "artifactSha256": entry["artifactSha256"], "anchorable": False, "frame": None,
                  "partMap": {"p:source#0": "p:rail-0#0"}}
        payload = triangle_glb()
        identity.validate_includes([record], raw, gltf(identity.bind_includes(payload, [record])))
        self.assertEqual(identity.bind_includes(payload, []), payload)
        record["anchorable"] = True
        record["frame"] = {"yaw": 0, "translation": [0, 0, 0]}
        with self.assertRaises(ValueError):
            identity.validate_includes([record], raw, gltf(identity.bind_includes(payload, [record])))


if __name__ == "__main__":
    unittest.main()
