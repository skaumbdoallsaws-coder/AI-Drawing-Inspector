"""MB3 catalog authority and artifact paging; all catalog paths are temporary."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from ai_inspector.industrial_assets.model_builder_host import IncludeCatalog, inspect_model_include
from ai_inspector.industrial_assets.model_builder.errors import ModelBuildError
from tests.model_builder_test_support import gltf, module, recipe
from tests.model_builder_composition_support import CatalogFixture, credit, edit_glb, triangle_glb


def test_artifact_hierarchy_keys_match_component_inventory_not_overview(tmp_path):
    from ai_inspector.codex_runtime.component_inventory import material_slots
    fixtures = CatalogFixture(tmp_path)
    payload = triangle_glb(copies=2, duplicate=True)
    asset = fixtures.add("artifact", payload)
    (tmp_path / "generated/fixtures/unused-overview.glb").write_bytes(triangle_glb())
    entry, inspected = fixtures.include(asset)
    assert inspected["representation"] == "artifact" and inspected["total"] == 2
    assert [p["key"] for p in inspected["parts"]] == [p["key"] for p in material_slots(gltf(payload))]
    assert inspected["artifactSha256"] == sha256(payload).hexdigest()
    sources = fixtures.catalog.resolve_recipe(module("recipe").normalize_recipe(recipe(entry)))
    assert sources["host"]["payload"] == payload


def test_default_resolver_uses_real_binder_and_raw_artifact_from_temp_catalog(tmp_path):
    from ai_inspector.industrial_assets.authored_library import CATALOG
    fixtures = CatalogFixture(tmp_path)
    asset = fixtures.add("binder", triangle_glb(copies=2, duplicate=True))
    path = tmp_path / CATALOG
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schemaVersion": 1, "assets": fixtures.records}), encoding="utf-8")
    (tmp_path / "generated/fixtures/binder.overview.glb").write_bytes(triangle_glb())
    catalog = IncludeCatalog(tmp_path)
    inspected = inspect_model_include({"assetId": asset}, catalog=catalog)
    assert inspected["total"] == 2 and inspected["size"] == fixtures.records[0]["dimensions"]
    entry = {"include": asset, "id": "host", "name": "host", "revision": inspected["revision"],
             "artifactSha256": inspected["artifactSha256"]}
    assert catalog.resolve_recipe(module("recipe").normalize_recipe(recipe(entry)))["host"]["payload"] == triangle_glb(copies=2, duplicate=True)


@pytest.mark.parametrize("kind", ["cc-by-nc", "cc-by-nd", "cc-by-nc-sa", "cc-by-nc-nd", "unknown", "other"])
def test_restricted_or_unknown_licence_refuses_with_include_identity(tmp_path, kind):
    fixtures = CatalogFixture(tmp_path)
    asset = fixtures.add("licence", triangle_glb(), attribution=credit(kind))
    with pytest.raises(ModelBuildError) as caught:
        fixtures.catalog.resolve(asset)
    assert caught.value.code == "include_licence" and asset in caught.value.problem


@pytest.mark.parametrize("kind", ["cc0", "cc-by", "cc-by-sa"])
def test_supported_catalog_licence_and_credit_projection(tmp_path, kind):
    fixtures = CatalogFixture(tmp_path)
    asset = fixtures.add("licence", triangle_glb(), source={}, attribution=credit(kind))
    item = fixtures.catalog.resolve(asset)
    assert item["manifest"]["attribution"] == (None if kind == "cc0" else credit(kind))


@pytest.mark.parametrize("source", [{}, {"kind": "own"}, {"kind": "imported", "license": "own"}])
def test_own_claims_in_glb_or_unrecognised_catalog_fields_are_not_authorship(tmp_path, source):
    fixtures = CatalogFixture(tmp_path)
    payload = edit_glb(triangle_glb(), lambda d: d["asset"].update(extras={"license": "own", "buildProvenance": {"own": True}}))
    asset = fixtures.add("untrusted", payload, source=source)
    with pytest.raises(ModelBuildError) as caught:
        fixtures.catalog.resolve(asset)
    assert caught.value.code == "include_licence"


@pytest.mark.parametrize("kind", ["authored-primitive", "basic-shape", "authored-recipe"])
def test_catalog_authorship_without_attribution_is_allowed(tmp_path, kind):
    fixtures = CatalogFixture(tmp_path)
    asset = fixtures.add("own", triangle_glb(), source={"kind": kind})
    assert fixtures.catalog.resolve(asset)["manifest"]["attribution"] is None


def test_catalog_provenance_does_not_override_credit_or_licence_conflict(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    asset = fixtures.add("provenance", triangle_glb(), source={})
    fixtures.records[0]["buildProvenance"] = {"generator": "model-builder-1"}
    assert fixtures.catalog.resolve(asset)["manifest"]["attribution"] is None
    fixtures.records[0]["attribution"] = credit("cc-by-nc")
    with pytest.raises(ModelBuildError, match="Unsupported include licence"):
        fixtures.catalog.resolve(asset)
    fixtures.records[0]["attribution"] = {**credit(), "license": "CC BY-NC 4.0"}
    with pytest.raises(ModelBuildError, match="Conflicting include licence"):
        fixtures.catalog.resolve(asset)


@pytest.mark.parametrize("pin", ["revision", "artifactSha256"])
def test_build_and_page_pins_refuse_changes(tmp_path, pin):
    fixtures = CatalogFixture(tmp_path)
    asset = fixtures.add("pinned", triangle_glb(copies=2))
    entry, inspected = fixtures.include(asset)
    if pin == "revision":
        fixtures.rows[0]["assetDefinitionRevision"] = "f"*64
    else:
        (tmp_path / fixtures.records[0]["artifact"]).write_bytes(triangle_glb(copies=3))
    with pytest.raises(ModelBuildError) as caught:
        inspect_model_include({"assetId": asset, "offset": 1, pin: inspected[pin]}, catalog=fixtures.catalog)
    assert caught.value.code == "include_mismatch" and caught.value.path.endswith("." + pin)
    with pytest.raises(ModelBuildError) as caught:
        fixtures.catalog.resolve_recipe(module("recipe").normalize_recipe(recipe(entry)))
    assert caught.value.code == "include_mismatch"


def test_paging_trims_to_48k_without_skipping_or_reordering_parts(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    def names(doc):
        for i, node in enumerate(doc["nodes"]):
            node["name"] = f"Generic member {i} " + "x"*450
    asset = fixtures.add("pages", edit_glb(triangle_glb(copies=200), names))
    request, keys = {"assetId": asset, "limit": 200}, []
    while True:
        page = inspect_model_include(request, catalog=fixtures.catalog)
        assert len(module("errors").json_bytes(page)) <= 48*1024
        assert page["total"] == 200 and page["parts"]
        keys.extend(p["key"] for p in page["parts"])
        if page["nextOffset"] is None:
            break
        request.update(offset=page["nextOffset"], revision=page["revision"], artifactSha256=page["artifactSha256"])
    assert len(keys) == len(set(keys)) == 200
    assert inspect_model_include({"assetId": asset, "offset": 200}, catalog=fixtures.catalog)["parts"] == []


@pytest.mark.parametrize("field,value", [("limit", 201), ("limit", True), ("offset", -1), ("revision", "bad"),
                                       ("artifactSha256", "bad"), ("sourcePath", "forbidden.glb")])
def test_inspection_schema_rejects_invalid_inputs(tmp_path, field, value):
    with pytest.raises(ModelBuildError) as caught:
        inspect_model_include({"assetId": "asset-test-any", field: value}, catalog=IncludeCatalog(tmp_path))
    assert caught.value.code == "schema_invalid"


def test_missing_unsafe_and_oversize_artifacts(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    with pytest.raises(ModelBuildError) as caught:
        fixtures.catalog.resolve("asset-test-missing")
    assert caught.value.code == "include_missing"
    asset = fixtures.add("test", triangle_glb())
    target = tmp_path / fixtures.records[0]["artifact"]
    target.unlink()
    with pytest.raises(ModelBuildError) as caught:
        fixtures.catalog.resolve(asset)
    assert caught.value.code == "include_missing"
    target.write_bytes(b"x"*(8*1024*1024+1))
    with pytest.raises(ModelBuildError) as caught:
        fixtures.catalog.resolve(asset)
    assert caught.value.code == "budget_exceeded"
    fixtures.records[0]["artifact"] = "../foreign.glb"
    with pytest.raises(ModelBuildError) as caught:
        fixtures.catalog.resolve(asset)
    assert caught.value.code == "include_invalid"


def test_catalog_mutation_during_read_refuses(tmp_path):
    fixtures = CatalogFixture(tmp_path)
    asset = fixtures.add("race", triangle_glb())
    calls = []
    def provider():
        rows = deepcopy(fixtures.rows)
        if calls:
            rows[0]["assetDefinitionRevision"] = "d"*64
        calls.append(True)
        return rows
    fixtures.catalog.catalog_provider = provider
    with pytest.raises(ModelBuildError) as caught:
        fixtures.catalog.resolve(asset)
    assert caught.value.code == "include_mismatch"
