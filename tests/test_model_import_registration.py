"""MI2b: real frozen geometry on temporary roots, with no server or private downloads.

Fast tests use protocol-shaped inspect pictures and the real recipe/writer for
drafts. The existing real-worker store smoke separately exercises subprocesses.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import threading
import time
from types import SimpleNamespace

import pytest

from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout import model_import_files as disk
from ai_inspector.facility_layout.model_import_registration import _bounded
from ai_inspector.facility_layout.model_import_store import ModelImportScope, ModelImportStore
from ai_inspector.industrial_assets import authored_library as library
from ai_inspector.industrial_assets.model_import.prepare import build_draft, part_record
from ai_inspector.industrial_assets.model_import.reader import read_model
from ai_inspector.industrial_assets.model_import.identity import asset_identity
from ai_inspector.industrial_assets.model_import.prepare_protocol import PUBLIC_FIELDS
from tests.model_import_store_support import PNG, WEBP, inspect_worker, manifest, recipe, upload
from tests.model_import_test_support import module, textured_box
from tests.test_model_import_catalog import project, placement, CREDIT


def write_draft(source, raw_recipe, destination, cancel, *, dependency_root):
    """Real transforms/writer with cheap deterministic picture fixtures."""
    payload = source.read_bytes()
    model = read_model(payload)
    draft, glb, model = build_draft(model, raw_recipe, payload)
    destination.mkdir()
    files = {"model.glb": glb, "draft.json": disk.encode(draft), "preview.png": PNG,
             "thumbnail.webp": WEBP,
             "CREDITS.txt": module("credit").credits_text(draft["attribution"]).encode(),
             "parts.jsonl": b"".join(disk.encode(part_record(p)) + b"\n" for p in model.parts)}
    for name, data in files.items():
        (destination / name).write_bytes(data)
    manifest(destination, "manifest.json", 2, files)
    return {key: draft[key] for key in PUBLIC_FIELDS}


@pytest.fixture
def setup(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=True, private_asset_root=project(tmp_path))
    host.ensure_bootstrap()
    store = ModelImportStore(host.layout_repository.root, layout_reader=host.service.get_layout,
                             runtime=lambda: SimpleNamespace(dependency_root=tmp_path),
                             inspect_worker=inspect_worker, prepare_worker=write_draft)
    host.service._model_import_store = store
    principal = host.principal()
    scope = ModelImportScope(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    reference = {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}
    record = upload(store, scope, textured_box().bytes())
    draft = store.prepare(scope, recipe(record["id"], attribution=CREDIT))
    try:
        yield SimpleNamespace(host=host, store=store, principal=principal, scope=scope,
                              reference=reference, record=record, draft=draft)
    finally:
        host.close()


def register(context, draft=None):
    return context.host.register_imported_asset(context.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                                (draft or context.draft)["draftId"])


def binding(context, principal=None, **updates):
    principal = principal or context.principal
    return {**context.reference, "tenantId": principal.tenant_id, "principalId": principal.principal_id, **updates}


def error(call, code, status=None):
    with pytest.raises(FacilityLayoutError) as caught:
        call()
    assert caught.value.code == code, caught.value.to_dict()
    if status is not None:
        assert caught.value.status_code == status
    return caught.value


def test_live_registration_receipt_bundle_and_repeat_without_rebuilding(setup, monkeypatch):
    c = setup
    draft_id = c.draft["draftId"]
    frozen = c.store.draft(c.scope, draft_id)
    directory = c.store.root / c.scope.key / "drafts" / draft_id
    original = (directory / "model.glb").read_bytes()
    monkeypatch.setattr(c.store, "prepare_worker", lambda *a, **kw: pytest.fail("Registration must not rebuild"))
    before = c.host.list_assets()["catalogVersion"]
    first = c.host.agent_runtime.model_import_register(c.principal, c.reference, draft_id)
    assert set(first) == {"assetId", "assetDefinitionRevision", "displayName", "category",
                          "dimensions", "attribution", "added"}
    assert first["added"] is True and first["assetId"] == asset_identity(frozen)["assetId"]
    assert first["dimensions"] == c.draft["dimensions"] and first["attribution"] == c.draft["attribution"]
    bound = c.host._catalog[first["assetId"]]
    assert "dimensions" not in bound  # The real binder exposes size through geometry.
    for key in ("assetId", "assetDefinitionRevision", "displayName", "category", "attribution"):
        assert first[key] == bound[key]
    aabb = bound["definition"]["geometry"]["aabb"]
    assert first["dimensions"] == pytest.approx({
        name: aabb["maximum"][axis] - aabb["minimum"][axis]
        for name, axis in (("width", "x"), ("height", "y"), ("depth", "z"))})
    assert c.host.list_assets()["catalogVersion"] != before
    receipt = c.store.receipt(c.scope, draft_id)
    assert receipt["assetId"] == first["assetId"] and receipt["revision"] == first["assetDefinitionRevision"]
    assert c.store.get(c.scope, c.record["id"])["registrations"] == [receipt]
    folder = c.host._component_visual_root / library.BUNDLE_FOLDER / first["assetId"]
    assert {p.name for p in folder.iterdir()} == set(library.BUNDLE_FILES)
    assert (folder / "model.glb").read_bytes() == original
    assert json.loads((folder / "bundle.json").read_bytes())["identity"] == asset_identity(frozen)["identity"]
    assert (folder / "CREDITS.txt").read_bytes() == module("credit").credits_text(first["attribution"]).encode()
    assert sorted(p.name for p in directory.iterdir()) == ["draft.json", "manifest.json", "parts.jsonl", "preview.png"]
    before_bytes = {p.name: p.read_bytes() for p in folder.iterdir()}
    second = register(c)
    assert second == {**first, "added": False}
    assert c.store.receipt(c.scope, draft_id) == receipt  # Repeat does not change receipt time.
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before_bytes


def test_registered_metadata_preview_and_repeat_survive_sweep_and_restart(setup):
    c = setup
    first = register(c)
    c.store.sweep(now=time.time() + 100 * 86400)
    restarted = LocalFacilityLayoutHost(c.host.root, private_assets=True,
                                        private_asset_root=c.host._component_visual_root)
    try:
        restarted.ensure_bootstrap()
        result = restarted.register_imported_asset(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, c.draft["draftId"])
        assert result == {**first, "added": False}
        summary, picture = restarted.agent_runtime.model_import_inspect(c.principal, c.reference, draft_id=c.draft["draftId"])
        assert summary["draftId"] == c.draft["draftId"] and summary["partsTotal"] == c.draft["partsTotal"]
        assert picture == PNG
        assert restarted._catalog[first["assetId"]]["assetDefinitionRevision"] == first["assetDefinitionRevision"]
    finally:
        restarted.close()


def test_second_registration_keeps_placed_revision_bytes_and_saved_layout(setup):
    c = setup
    first = register(c)
    original_definition = deepcopy(c.host._asset_versions[(first["assetId"], first["assetDefinitionRevision"])])
    model = c.host._component_visual_root / library.BUNDLE_FOLDER / first["assetId"] / "model.glb"
    original_bytes = model.read_bytes()
    c.host.service.apply_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, c.reference["revision"],
        [{"op": "place_asset", "placementId": "pl-import", "placement": placement(first)}])
    saved = c.host.service.get_layout(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    other_draft = c.store.prepare(c.scope, recipe(c.record["id"], name="Smaller import", size={"scale": .5},
                                                 attribution=CREDIT))
    other = register(c, other_draft)
    assert other["assetId"] != first["assetId"]
    assert c.host._asset_versions[(first["assetId"], first["assetDefinitionRevision"])] == original_definition
    assert model.read_bytes() == original_bytes
    assert c.host.service.get_layout(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved
    # A successful placement legitimately changes the reference during a turn.
    assert first["assetId"] in c.host.agent_runtime.registrations_since(binding(c), 0)


@pytest.mark.parametrize("two_hosts", [False, True])
def test_concurrent_registration_returns_one_added_and_identical_repeats(setup, two_hosts):
    c = setup
    other = (LocalFacilityLayoutHost(c.host.root, private_assets=True, private_asset_root=c.host._component_visual_root)
             if two_hosts else c.host)
    try:
        other.ensure_bootstrap()
        barrier = threading.Barrier(6)
        def perform(i):
            barrier.wait()
            host = other if i % 2 else c.host
            return host.register_imported_asset(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, c.draft["draftId"])
        with ThreadPoolExecutor(max_workers=6) as pool:
            values = list(pool.map(perform, range(6)))
        assert sum(v["added"] for v in values) == 1
        assert len({v["assetId"] for v in values}) == len({v["assetDefinitionRevision"] for v in values}) == 1
        assert len(c.store.get(c.scope, c.record["id"])["registrations"]) == 1
        assert len(json.loads((c.host._component_visual_root / library.CATALOG).read_bytes())["assets"]) == 1
    finally:
        if two_hosts:
            other.close()


@pytest.mark.parametrize("point", ["catalog_write", "bind", "receipt", "after_receipt"])
def test_publication_failure_is_visible_or_retryable_without_rebuilding(setup, monkeypatch, point):
    c = setup
    frozen = c.store.draft(c.scope, c.draft["draftId"])
    asset_id = asset_identity(frozen)["assetId"]
    with monkeypatch.context() as patch:
        if point == "catalog_write":
            patch.setattr(library, "replace_file", lambda *a, **kw: (_ for _ in ()).throw(OSError("publish failed")))
        elif point == "bind":
            patch.setattr(c.host, "bind_installed_asset", lambda *a: (_ for _ in ()).throw(
                FacilityLayoutError("authored_asset_unbound", "Injected bind failure")))
        else:
            original = c.store.record_receipt
            def broken(*args, **kwargs):
                if point == "after_receipt":
                    original(*args, **kwargs)
                raise OSError("Injected receipt interruption")
            patch.setattr(c.store, "record_receipt", broken)
        with pytest.raises(FacilityLayoutError):
            register(c)
    folder = c.host._component_visual_root / library.BUNDLE_FOLDER / asset_id
    original_bytes = {p.name: p.read_bytes() for p in folder.iterdir()}
    if point != "catalog_write":
        assert asset_id in {a["assetId"] for a in c.host.list_assets()["assets"]}
    monkeypatch.setattr(c.store, "prepare_worker", lambda *a, **kw: pytest.fail("Retry must use frozen bytes"))
    result = register(c)
    assert result["assetId"] == asset_id and result["added"] == (point == "catalog_write")
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == original_bytes
    assert c.store.receipt(c.scope, c.draft["draftId"])["assetId"] == asset_id


@pytest.mark.parametrize("filename", ["model.glb", "thumbnail.webp", "CREDITS.txt", "bundle.json"])
def test_repeat_verifies_installed_bundle_after_compaction(setup, filename):
    c = setup
    result = register(c)
    path = c.host._component_visual_root / library.BUNDLE_FOLDER / result["assetId"] / filename
    if filename == "bundle.json":
        value = json.loads(path.read_bytes())
        value["identity"]["engine"] = "different"
        path.write_bytes(disk.encode(value))
    else:
        path.write_bytes(path.read_bytes() + b"tampered")
    error(lambda: register(c), "asset_identity_conflict", 409)


def test_receipt_written_immediately_after_live_swap(setup, monkeypatch):
    c = setup
    original = c.store.record_receipt
    seen = []
    def check(scope, draft_id, asset_id, revision, **kw):
        assert c.host._catalog[asset_id]["assetDefinitionRevision"] == revision
        assert c.store._receipt(scope, draft_id) is None
        seen.append(asset_id)
        return original(scope, draft_id, asset_id, revision, **kw)
    monkeypatch.setattr(c.store, "record_receipt", check)
    result = register(c)
    assert seen == [result["assetId"]]


def test_sweep_does_not_delete_draft_while_registration_holds_it(setup, monkeypatch):
    c = setup
    original = library.install_bundle
    directory = c.store.root / c.scope.key / "drafts" / c.draft["draftId"]
    def publishing(*args, **kwargs):
        c.store.sweep(now=time.time() + 100 * 86400)
        assert (directory / "model.glb").is_file()
        return original(*args, **kwargs)
    monkeypatch.setattr(library, "install_bundle", publishing)
    assert register(c)["added"] is True


def test_scope_and_permission_are_checked_by_every_boundary(setup, monkeypatch):
    c = setup
    viewer = FacilityPrincipal("viewer", c.principal.tenant_id, (LOCAL_SITE_ID,), ("viewer",))
    runtime = c.host.agent_runtime
    error(lambda: c.host.register_imported_asset(viewer, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, c.draft["draftId"]),
          "role_not_authorized", 403)
    error(lambda: runtime.model_import_register(viewer, c.reference, c.draft["draftId"]), "role_not_authorized", 403)
    error(lambda: runtime.model_import_prepare(viewer, c.reference, {}, threading.Event()), "role_not_authorized", 403)
    assert runtime.model_import_inspect(viewer, c.reference, import_id=c.record["id"])[1] == PNG
    assert runtime.describe_model_attachment(viewer, binding(c, viewer), c.record["id"])["state"] == "ready"
    assert runtime.registrations_since(binding(c, viewer), 0) == []
    # Supply an authorized alternate layout reader so these reach the import's
    # own tenant/site checks, not just a missing layout in the repository.
    monkeypatch.setattr(c.host.service, "get_layout", lambda *args: {"revision": c.reference["revision"]})
    c.store.layout_reader = c.host.service.get_layout
    foreign = FacilityPrincipal("other", "other-tenant", (LOCAL_SITE_ID, "other-site"), ("editor",))
    other_site = FacilityPrincipal("site-user", c.principal.tenant_id, (LOCAL_SITE_ID, "other-site"), ("editor",))
    for person, ref in ((foreign, c.reference), (other_site, {**c.reference, "siteId": "other-site"})):
        error(lambda: runtime.model_import_register(person, ref, c.draft["draftId"]), "model_import_missing", 404)
        error(lambda: runtime.model_import_inspect(person, ref, import_id=c.record["id"]), "model_import_missing", 404)
        error(lambda: runtime.model_import_inspect(person, ref, draft_id=c.draft["draftId"]), "model_import_missing", 404)
        error(lambda: runtime.model_import_prepare(person, ref, recipe(c.record["id"]), threading.Event()),
              "model_import_missing", 404)
        b = {**ref, "tenantId": person.tenant_id, "principalId": person.principal_id}
        assert runtime.describe_model_attachment(person, b, c.record["id"]) is None
        assert runtime.registrations_since(b, 0) == []
    assert json.loads((c.host._component_visual_root / library.CATALOG).read_bytes())["assets"] == []


def test_stale_reference_and_spoofed_binding_are_refused_before_store_work(setup, monkeypatch):
    c = setup
    hooks = c.host.agent_runtime
    stale = {**c.reference, "revision": "old-revision"}
    for action in (lambda: hooks.model_import_inspect(c.principal, stale),
                   lambda: hooks.model_import_prepare(c.principal, stale, {}, threading.Event()),
                   lambda: hooks.model_import_register(c.principal, stale, c.draft["draftId"]),
                   lambda: hooks.describe_model_attachment(c.principal, {**binding(c), **stale}, c.record["id"])):
        error(action, "codex_document_unavailable", 409)
    for updates in ({"tenantId": "foreign"}, {"principalId": "foreign"}):
        error(lambda: hooks.describe_model_attachment(c.principal, binding(c, **updates), c.record["id"]),
              "model_import_missing", 404)
        error(lambda: hooks.registrations_since(binding(c, **updates), 0), "model_import_missing", 404)


def test_hook_shapes_paging_preparation_and_bounded_errors(setup):
    c = setup
    hooks = c.host.agent_runtime
    listing, picture = hooks.model_import_inspect(c.principal, c.reference)
    assert picture is None and listing["imports"][0]["importId"] == c.record["id"]
    source, picture = hooks.model_import_inspect(c.principal, c.reference, import_id=c.record["id"], limit=1)
    assert source["partsTotal"] == 1 and picture == PNG
    draft, picture = hooks.model_import_inspect(c.principal, c.reference, draft_id=c.draft["draftId"], limit=1)
    assert draft["partsOffset"] == 0 and draft["draftId"] == c.draft["draftId"] and picture == PNG
    prepared, picture = hooks.model_import_prepare(c.principal, c.reference, recipe(c.record["id"], name="New"),
                                                   threading.Event())
    assert prepared["draftId"] != c.draft["draftId"] and picture == PNG
    for value in (listing, source, draft, prepared):
        assert len(disk.encode(value)) <= 48 * 1024
    bad = error(lambda: hooks.model_import_prepare(c.principal, c.reference, {"name": "X", "category": "decor"},
                                                  threading.Event()), "recipe_invalid", 422)
    assert {"path": "importId", "problem": "required"} in bad.details["problems"]
    assert bad.to_dict()["details"] == bad.details
    bad = error(lambda: hooks.model_import_prepare(c.principal, c.reference,
        recipe(c.record["id"], parts=[{"select": {"material": "nonexistent"}}]), threading.Event()),
        "recipe_selector_empty", 422)
    assert bad.details["problems"][0]["path"] == "parts[0].select.material"
    assert "closest" in bad.details and len(disk.encode(bad.to_dict())) <= 8192
    error(lambda: hooks.model_import_inspect(c.principal, c.reference,
          import_id=c.record["id"], draft_id=c.draft["draftId"]), "model_reference_invalid", 422)
    for options in ({"offset": -1}, {"offset": True}, {"limit": 65}, {"limit": 0}):
        error(lambda: hooks.model_import_inspect(c.principal, c.reference, **options), "model_parts_page_invalid", 422)


def test_attachment_description_does_not_reconcile_and_bounds_refusal(setup):
    c = setup
    record_path = c.store.root / c.scope.key / "imports" / (c.record["id"] + ".json")
    raw = disk.read_json(record_path)
    raw.update(state="failed", name="../../" + "X" * 90 + ".glb",
               refusal={"code": "worker_failed", "message": "Y" * 2000})
    disk.atomic(record_path, raw)
    before = record_path.read_bytes()
    description = c.host.agent_runtime.describe_model_attachment(c.principal, binding(c), c.record["id"])
    assert set(description) == {"importId", "name", "format", "megabytes", "state", "refusal"}
    assert len(description["name"]) <= 80 and "/" not in description["name"]
    assert len(description["refusal"]["message"]) == 1000 and description["megabytes"] > 0
    assert record_path.read_bytes() == before
    refused, picture = c.host.agent_runtime.model_import_inspect(c.principal, c.reference, import_id=c.record["id"])
    assert refused["state"] == "failed" and picture is None
    assert c.host.agent_runtime.describe_model_attachment(c.principal, binding(c), "mi-" + "f" * 24) is None


def test_registration_notifications_come_from_receipts_and_are_read_authorized(setup, monkeypatch):
    c = setup
    runtime = c.host.agent_runtime
    started = time.time()
    first = register(c)
    receipt = c.store.receipt(c.scope, c.draft["draftId"])
    assert runtime.registrations_since(binding(c), started) == [first["assetId"]]
    assert runtime.registrations_since(binding(c), receipt["at"]) == [first["assetId"]]
    assert runtime.registrations_since(binding(c), receipt["at"] + 1) == []
    for value in (-1, True, float("nan"), float("inf"), 10 ** 10000, "yesterday"):
        error(lambda: runtime.registrations_since(binding(c), value), "model_registration_time_invalid", 422)
    # No role/site authority can be smuggled in through the binding IDs.
    none = FacilityPrincipal(c.principal.principal_id, c.principal.tenant_id, (LOCAL_SITE_ID,), ("catalog_curator",))
    c.host._model_import_hooks.remember_principal(none)
    error(lambda: runtime.registrations_since(binding(c), started), "role_not_authorized", 403)


def test_custom_resolved_principal_is_available_to_receipt_hook_without_model_calls(setup):
    c = setup
    person = FacilityPrincipal("custom-viewer", c.principal.tenant_id, (LOCAL_SITE_ID,), ("viewer",))
    c.host._principal_resolver = lambda request: person
    assert c.host.resolve_principal(None) == person
    assert c.host.agent_runtime.registrations_since(binding(c, person), 0) == []


def test_summary_paging_additions_cannot_exceed_48k():
    result = {"draftId": "md-" + "a" * 24, "partsTotal": 64, "partsOffset": 12,
              "parts": [{"key": f"p{i}", "name": "\u4e00" * 300} for i in range(64)], "nextPartsOffset": None}
    bounded = _bounded(result)
    assert len(disk.encode(bounded)) <= 48 * 1024
    assert bounded["nextPartsOffset"] == 12 + len(bounded["parts"])
    assert len(result["parts"]) == 64


def test_bounded_last_part_keeps_paging_progress():
    value = {"partsTotal": 2, "partsOffset": 0, "parts": [{"key": "p0", "name": "one"}],
             "nextPartsOffset": 1, "materialsTotal": 2,
             "materials": [{"name": "A" * (26 * 1024)}, {"name": "B" * (26 * 1024)}]}
    result = _bounded(value)
    assert result["parts"] == value["parts"] and result["nextPartsOffset"] == 1
    assert len(result["materials"]) == 1 and len(disk.encode(result)) <= 48 * 1024


def test_registration_receipt_uses_its_existing_peak_reservation(setup):
    c = setup
    # hold_draft reserves record bytes plus 16 KiB. There is room for that,
    # but an erroneous second 4 KiB charge would reject after publication.
    folder = c.store.root / c.scope.key
    record_bytes = disk.size(folder / "imports" / (c.record["id"] + ".json"))
    c.store.site_bytes = disk.size(folder) + record_bytes + 16 * 1024
    result = register(c)
    assert result["added"] is True
    assert c.store.receipt(c.scope, c.draft["draftId"])["assetId"] == result["assetId"]
    assert disk.size(c.store.root / c.scope.key) <= c.store.site_bytes
