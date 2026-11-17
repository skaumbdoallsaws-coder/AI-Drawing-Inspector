"""MB4a bundles and live binding on temporary catalogs only; no Sage wiring."""
from copy import deepcopy
from hashlib import sha256
import json
import threading
import time
from types import SimpleNamespace

import pytest

from ai_inspector.facility_layout import model_import_files as disk
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.host import LOCAL_SITE_ID, LOCAL_LAYOUT_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.model_import_store import ModelImportScope, ModelImportStore
from ai_inspector.facility_layout.private_catalog import private_asset_spec, project_private_asset
from ai_inspector.industrial_assets import authored_library as library, model_builder_bundle as bundles
from ai_inspector.industrial_assets.model_builder.identity import asset_identity
from ai_inspector.industrial_assets.model_builder_host import IncludeCatalog, inspect_model_include
from tests.model_builder_draft_support import project, write_build, build
from tests.model_builder_test_support import recipe, shape
from tests.model_builder_composition_support import CatalogFixture, cube_payload, credit
from tests.model_import_store_support import inspect_worker, PNG, upload, recipe as import_recipe


@pytest.fixture
def context(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=True, private_asset_root=project(tmp_path))
    host.ensure_bootstrap()
    store = ModelImportStore(host.layout_repository.root, layout_reader=host.service.get_layout,
                             runtime=lambda: SimpleNamespace(dependency_root=tmp_path), build_worker=write_build,
                             inspect_worker=inspect_worker)
    host.service._model_import_store = store
    principal = host.principal()
    scope = ModelImportScope(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    reference = {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}
    try:
        yield SimpleNamespace(host=host, store=store, principal=principal, scope=scope, reference=reference)
    finally:
        host.close()


def register(c, draft):
    return c.host.register_imported_asset(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, draft["draftId"])


def folder(c, asset_id):
    return c.host._component_visual_root / bundles.FOLDER / asset_id


def refused(call, code):
    with pytest.raises(FacilityLayoutError) as caught:
        call()
    assert caught.value.code == code, caught.value.to_dict()


def include(c, asset_id, **extra):
    info = inspect_model_include({"assetId": asset_id}, catalog=IncludeCatalog(c.host._component_visual_root))
    return {"id": "host", "name": "host", "include": asset_id, "revision": info["revision"],
            "artifactSha256": info["artifactSha256"], **extra}


def add_credited(c, kind="cc-by"):
    fixture = CatalogFixture(c.host._component_visual_root)
    asset_id = fixture.add("credited", cube_payload(), attribution=credit(kind))
    target = c.host._component_visual_root / library.CATALOG
    value = json.loads(target.read_bytes())
    value["assets"].extend(fixture.records)
    target.write_bytes(disk.encode(value))
    return asset_id


def test_host_build_inspect_register_repeat_reload_and_compaction(context):
    c = context
    from ai_inspector.facility_layout.reference_files import ReferenceStore
    from ai_inspector.facility_layout.model_import_runtime import model_import_runtime
    references = ReferenceStore(c.host.service, dependency_root=model_import_runtime().dependency_root)
    c.host.service._reference_store = references
    upload = references.begin_upload(c.scope, "example.png", len(PNG))
    upload.write(PNG)
    reference_id = upload.finish()["referenceId"]
    for _ in range(100):
        if references.get(c.scope, reference_id)["state"] == "ready":
            break
        time.sleep(.05)
    assert references.get(c.scope, reference_id)["state"] == "ready"
    raw = recipe(references=[reference_id], sizeBasis={"kind": "research", "note": "Generic example size",
                  "sources": [{"url": "https://example.org/spec", "title": "Example specification"}]})
    result, picture = c.host.build_model_draft(c.principal, c.reference, raw)
    assert picture == PNG
    frozen = c.store.draft(c.scope, result["draftId"])
    directory = c.store.root / c.scope.key / "drafts" / result["draftId"]
    original = (directory / "model.glb").read_bytes()
    before_version = c.host.list_assets()["catalogVersion"]
    # The existing registration entry is already kind-aware. No new tool is wired.
    first = c.host.agent_runtime.model_import_register(c.principal, c.reference, result["draftId"])
    assert first["added"] is True and first["assetId"] == asset_identity(frozen)["assetId"]
    assert first["attribution"] is None and first["dimensions"] == frozen["catalogDimensions"]
    assert c.host.list_assets()["catalogVersion"] != before_version
    bound = c.host._catalog[first["assetId"]]
    assert bound["buildProvenance"] == frozen["buildProvenance"] == bound["definition"]["buildProvenance"]
    assert "Generic illustrative model built by Sage; size: research" in bound["description"]
    target = folder(c, first["assetId"])
    assert {p.name for p in target.iterdir()} == {"model.glb", "thumbnail.webp", "recipe.json", "bundle.json"}
    assert (target / "model.glb").read_bytes() == original
    manifest = json.loads((target / "bundle.json").read_bytes())
    assert manifest["kind"] == "build" and manifest["identity"] == asset_identity(frozen)["identity"]
    assert "references" not in json.loads((target / "recipe.json").read_bytes())
    assert reference_id.encode() not in b"".join(p.read_bytes() for p in target.iterdir())
    assert c.host.list_model_build_drafts(c.principal, c.reference) == []
    receipt = c.store.receipt(c.scope, result["draftId"])
    assert c.store.registrations_since(c.scope, 0) == [first["assetId"]]
    bytes_before = {p.name: p.read_bytes() for p in target.iterdir()}
    assert register(c, result) == {**first, "added": False}
    assert c.store.receipt(c.scope, result["draftId"]) == receipt
    assert {p.name: p.read_bytes() for p in target.iterdir()} == bytes_before
    assert {p.name for p in directory.iterdir()} == {"draft.json", "recipe.json", "result.json", "manifest.json", "preview.png"}
    restarted = LocalFacilityLayoutHost(c.host.root, private_assets=True, private_asset_root=c.host._component_visual_root)
    try:
        restarted.ensure_bootstrap()
        assert restarted._catalog[first["assetId"]]["definition"] == bound["definition"]
        assert restarted.register_imported_asset(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, result["draftId"]) == {**first, "added": False}
        summary, picture = restarted.agent_runtime.model_import_inspect(c.principal, c.reference, draft_id=result["draftId"])
        assert summary == result and picture == PNG
    finally:
        restarted.close()


@pytest.mark.parametrize("kind", [None, "cc0", "cc-by", "cc-by-sa"])
def test_credits_exactly_when_an_attributed_include_is_present(context, kind):
    c = context
    raw = recipe() if kind is None else recipe(include(c, add_credited(c, kind)))
    made, _ = c.host.build_model_draft(c.principal, c.reference, raw)
    frozen = c.store.draft(c.scope, made["draftId"])
    installed = register(c, made)
    target = folder(c, installed["assetId"])
    assert (target / "CREDITS.txt").exists() == (kind in ("cc-by", "cc-by-sa"))
    assert (installed["attribution"] is not None) == (kind in ("cc-by", "cc-by-sa"))
    if installed["attribution"]:
        assert (target / "CREDITS.txt").read_bytes() == bundles.module("credit").credits_text(installed["attribution"]).encode()
    manifest = json.loads((target / "bundle.json").read_bytes())
    assert manifest["includes"] == frozen["includes"]
    assert manifest["identity"]["includes"] == [{"assetId": v["assetId"], "revision": v["revision"],
        "representation": "artifact", "visualSha256": v["artifactSha256"]} for v in frozen["includes"]]
    assert register(c, made) == {**installed, "added": False}


@pytest.mark.parametrize("mode", ["plain", "repeated", "tilted"])
def test_registered_build_can_be_included_and_persists_anchor_contract(context, mode):
    c = context
    first = register(c, build(c.store, c.scope))
    leaf = include(c, first["assetId"], rotateY=25, position=[.3, 0, .2])
    entry = leaf
    if mode == "repeated":
        entry = {"id": "copies", "group": [leaf], "repeat": {"count": 2, "step": [1.1, 0, 0]}}
    elif mode == "tilted":
        entry = {"id": "tilted", "group": [leaf], "rotate": {"x": 10}}
    made, _ = c.host.build_model_draft(c.principal, c.reference, recipe(entry), derived_from=first["assetId"])
    result = register(c, made)
    assert result["attribution"] is None
    manifest = json.loads((folder(c, result["assetId"]) / "bundle.json").read_bytes())
    assert manifest["buildProvenance"]["derivedFrom"] == first["assetId"]
    record = manifest["includes"][0]
    assert record["anchorable"] is (mode == "plain")
    assert (record["frame"] is None) is (mode != "plain")
    assert record["partMap"] and all(k.startswith("p:") for k in record["partMap"])
    assert "source" not in next(v for v in json.loads((c.host._component_visual_root / library.CATALOG).read_bytes())["assets"]
                                 if v["assetId"] == first["assetId"])


def test_hung_model_registers_catalog_height_and_keeps_spatial_geometry(context):
    c = context
    made = build(c.store, c.scope, recipe(hangHeight=1.2))
    installed = register(c, made)
    assert installed["dimensions"]["height"] == pytest.approx(2.2)
    definition = c.host._catalog[installed["assetId"]]["definition"]
    from tests.test_model_import_catalog import placement
    c.host.service.apply_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, c.reference["revision"],
        [{"op": "place_asset", "placementId": "pl-built", "placement": placement(installed, name="pl-built")}])
    saved = c.host.service.get_layout(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    again = register(c, made)
    assert again == {**installed, "added": False}
    assert c.host.service.get_layout(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved
    assert c.host._asset_versions[(installed["assetId"], installed["assetDefinitionRevision"])]["definition"] == definition


@pytest.mark.parametrize("filename", ["model.glb", "recipe.json", "thumbnail.webp", "bundle.json"])
def test_installed_identity_conflicts_are_never_repaired(context, filename):
    c = context
    made = build(c.store, c.scope)
    installed = register(c, made)
    target = folder(c, installed["assetId"]) / filename
    before = target.read_bytes()
    if filename == "bundle.json":
        value = json.loads(before)
        value["identity"]["engine"] = "other"
        target.write_bytes(disk.encode(value))
    else:
        target.write_bytes(before+b"changed")
    broken = target.read_bytes()
    refused(lambda: register(c, made), "asset_identity_conflict")
    assert target.read_bytes() == broken


@pytest.mark.parametrize("point", ["bind", "receipt"])
def test_installed_but_unbound_or_unreceipted_build_is_retryable(context, monkeypatch, point):
    c = context
    made = build(c.store, c.scope)
    with monkeypatch.context() as patch:
        def fail(*a, **kw):
            raise FacilityLayoutError("injected", "Generic injected failure")
        patch.setattr(c.host if point == "bind" else c.store,
                      "bind_installed_asset" if point == "bind" else "record_receipt", fail)
        refused(lambda: register(c, made), "injected")
    assert c.store.receipt(c.scope, made["draftId"]) is None
    assert len(c.store.list_build_drafts(c.scope)) == 1
    result = register(c, made)
    assert result["added"] is False
    assert c.store.receipt(c.scope, made["draftId"])["assetId"] == result["assetId"]


def test_permissions_revision_scope_and_category_checked_before_host_build(context, monkeypatch):
    c = context
    viewer = FacilityPrincipal("viewer", c.principal.tenant_id, (LOCAL_SITE_ID,), ("viewer",))
    refused(lambda: c.host.build_model_draft(viewer, c.reference, recipe()), "role_not_authorized")
    stale = {**c.reference, "revision": "stale"}
    for action in (lambda: c.host.build_model_draft(c.principal, stale, recipe()),
                   lambda: c.host.list_model_build_drafts(c.principal, stale)):
        refused(action, "codex_document_unavailable")
    refused(lambda: c.host.build_model_draft(c.principal, c.reference, recipe(category="Unknown category")), "schema_invalid")
    refused(lambda: c.host.build_model_draft(c.principal, c.reference, recipe(), derived_from="asset-missing"), "asset_missing")
    made = build(c.store, c.scope)
    refused(lambda: c.host.agent_runtime.model_import_register(viewer, c.reference, made["draftId"]), "role_not_authorized")
    monkeypatch.setattr(c.host.service, "get_layout", lambda *a: {"revision": c.reference["revision"]})
    c.store.layout_reader = c.host.service.get_layout
    foreign = FacilityPrincipal("other", "other-tenant", (LOCAL_SITE_ID,), ("editor",))
    assert c.host.list_model_build_drafts(foreign, c.reference) == []
    refused(lambda: c.host.agent_runtime.model_import_register(foreign, c.reference, made["draftId"]), "model_import_missing")
    refused(lambda: c.host.agent_runtime.model_import_inspect(foreign, c.reference, draft_id=made["draftId"]), "model_import_missing")
    assert json.loads((c.host._component_visual_root / library.CATALOG).read_bytes())["assets"] == []


def test_revision_change_during_build_refuses_before_publication(context):
    c = context
    def changed(*args, **kwargs):
        result = write_build(*args, **kwargs)
        c.host.service.get_layout = lambda *a: {"revision": "changed"}
        return result
    c.store.build_worker = changed
    refused(lambda: c.host.build_model_draft(c.principal, c.reference, recipe()), "codex_document_unavailable")
    assert c.store.list_build_drafts(c.scope) == []


def test_projection_adds_only_optional_provenance_without_changing_legacy_spec(context):
    c = context
    made = build(c.store, c.scope)
    entry = bundles.catalog_entry(c.store.draft(c.scope, made["draftId"]))
    plain = deepcopy(entry)
    plain.pop("buildProvenance")
    assert private_asset_spec(entry) == private_asset_spec(plain)
    assert project_private_asset(plain) == private_asset_spec(plain)
    assert project_private_asset(entry)["build_provenance"] == entry["buildProvenance"]
    entry["buildProvenance"]["triangles"] = 60001
    with pytest.raises(ValueError):
        project_private_asset(entry)


def test_legacy_import_bundle_and_retained_draft_are_not_rewritten(context):
    c = context
    from tests.test_model_import_registration import write_draft
    from tests.model_import_test_support import textured_box
    from tests.test_model_import_catalog import CREDIT
    c.store.prepare_worker = write_draft
    record = upload(c.store, c.scope, textured_box().bytes())
    imported = c.store.prepare(c.scope, import_recipe(record["id"], attribution=CREDIT))
    installed = register(c, imported)
    legacy = c.host._component_visual_root / library.BUNDLE_FOLDER / installed["assetId"]
    retained = c.store.root / c.scope.key / "drafts" / imported["draftId"]
    paths = [*legacy.iterdir(), *retained.iterdir()]
    before = {p: p.read_bytes() for p in paths}
    assert "kind" not in json.loads((legacy / "bundle.json").read_bytes())
    register(c, build(c.store, c.scope))
    c.store.sweep()
    assert register(c, imported) == {**installed, "added": False}
    assert {p: p.read_bytes() for p in paths} == before
