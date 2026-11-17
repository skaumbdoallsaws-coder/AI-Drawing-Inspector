"""Small generated catalogs only: never touch the checkout's generated asset store."""
from copy import deepcopy
from hashlib import sha256
import json
import struct

from tests.model_builder_test_support import module, recipe, shape

contract = module("include_contract")


def pack_glb(document, binary=b""):
    doc = deepcopy(document)
    binary += b"\0" * (-len(binary) % 4)
    doc["buffers"] = [{"byteLength": len(binary)}]
    encoded = module("errors").json_bytes(doc)
    encoded += b" " * (-len(encoded) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 28+len(encoded)+len(binary))
            + struct.pack("<I4s", len(encoded), b"JSON") + encoded
            + struct.pack("<I4s", len(binary), b"BIN\0") + binary)


def edit_glb(payload, edit):
    size = struct.unpack_from("<I", payload, 12)[0]
    doc = json.loads(payload[20:20+size])
    binary = payload[28+size:]
    edit(doc)
    return pack_glb(doc, binary)


def triangle_glb(*, copies=1, triangles=1, duplicate=False, extras=None):
    """A synthetic indexed triangle; count overrides exercise pre-decode refusals."""
    binary = struct.pack("<9f3I", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 2)
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(copies))}],
           "nodes": [{"name": "rail" if duplicate else f"rail-{i}", "mesh": 0} for i in range(copies)],
           "meshes": [{"name": "rail mesh", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
           "materials": [{"name": "steel", "extras": extras or {}}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
                         {"bufferView": 1, "componentType": 5125, "count": triangles*3, "type": "SCALAR"}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36},
                           {"buffer": 0, "byteOffset": 36, "byteLength": 12}]}
    return pack_glb(doc, binary)


def credit(kind="cc-by"):
    labels = {"cc0": "CC0 1.0", "cc-by": "CC BY 4.0", "cc-by-sa": "CC BY-SA 4.0",
              "cc-by-nc": "CC BY-NC 4.0", "cc-by-nd": "CC BY-ND 4.0", "unknown": ""}
    return {"title": "Generic fixture", "author": "Example maker", "sourceUrl": "https://example.org/model",
            "license": labels.get(kind, kind), "licenseClass": kind, "statedBy": "user"}


class CatalogFixture:
    def __init__(self, root):
        from ai_inspector.industrial_assets.model_builder_host import IncludeCatalog
        self.root, self.records, self.rows = root, [], []
        self.catalog = IncludeCatalog(root, catalog_provider=lambda: deepcopy(self.rows),
                                      records_provider=lambda: deepcopy(self.records))

    def add(self, name, payload, *, dimensions=None, source=None, attribution=None, matrix=None, surfaces=False):
        relative = f"generated/fixtures/{name}.glb"
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        matrix = list(contract.IDENTITY if matrix is None else matrix)
        dimensions = dimensions or {"width": 1, "height": 1, "depth": 1}
        asset_id = "asset-test-" + name
        definition = {"coordinateFrame": {"sourceToCanonical": matrix}, "dimensions": dimensions,
                      "name": name}
        revision = sha256(module("errors").json_bytes(definition)).hexdigest()
        record = {"assetId": asset_id, "displayName": "Generic " + name, "category": "Material Handling",
                  "description": "Generated test fixture", "dimensions": dimensions, "artifact": relative,
                  "sourceToCanonical": matrix, "tags": [],
                  "source": {"kind": "authored-recipe"} if source is None else source}
        if attribution is not None:
            record["attribution"] = attribution
        if surfaces:
            record["supportSurfaces"] = [{"surfaceId": "top"}]
        self.records.append(record)
        self.rows.append({"assetId": asset_id, "assetDefinitionRevision": revision, "definition": definition,
                          "overview": {"path": "/generated/fixtures/unused-overview.glb"}})
        return asset_id

    def include(self, asset_id, **fields):
        from ai_inspector.industrial_assets.model_builder_host import inspect_model_include
        summary = inspect_model_include({"assetId": asset_id}, catalog=self.catalog)
        entry = {"id": "host", "name": "host", "include": asset_id,
                 "revision": summary["revision"], "artifactSha256": summary["artifactSha256"], **fields}
        return entry, summary

    def build(self, raw, **kwargs):
        normalized = module("recipe").normalize_recipe(raw, allowed_appearance_ids=kwargs.get("allowed_appearance_ids", ()))
        sources = self.catalog.resolve_recipe(normalized)
        return module("build").build_model(raw, include_sources=sources, **kwargs)


def cube_payload(**material):
    return module("build").build_model(recipe(shape(), materials={"paint": {"color": "#52708a", **material}}),
                                       allowed_appearance_ids=["steel"]).glb
