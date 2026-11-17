"""MB4a kind-aware store, publication, recovery and shared admission limits."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import json
import threading
import time

import pytest

from ai_inspector.facility_layout import model_import_files as disk, model_build_store
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.industrial_assets.model_builder.errors import ModelBuildError
from tests.model_builder_draft_support import store, build, write_build
from tests.model_builder_test_support import recipe
from tests.model_import_store_support import scope, upload, recipe as import_recipe, PNG


def refused(call, code):
    with pytest.raises(FacilityLayoutError) as caught:
        call()
    assert caught.value.code == code, caught.value.to_dict()


def test_build_draft_has_no_import_id_and_lists_and_inspects_after_restart(tmp_path):
    s, bound = store(tmp_path), scope()
    result = build(s, bound)
    value = s.draft(bound, result["draftId"])
    assert value["kind"] == "build" and "importId" not in value and "importId" not in value["recipe"]
    folder = s.root / bound.key
    assert not list((folder / "imports").glob("*")) and not list((folder / "sources").glob("*"))
    assert not list((folder / "jobs").glob("*")) and s._active() == []
    fresh = store(tmp_path)
    fresh.reconcile()
    assert fresh.list_build_drafts(bound) == [{"draftId": value["draftId"], "name": value["recipe"]["name"],
                                              "created": value["created"], "expires": value["expires"]}]
    assert fresh.draft_parts(bound, value["draftId"]) == result
    assert fresh.preview(bound, value["draftId"], draft=True) == PNG
    assert fresh.draft(bound, value["draftId"]) == value


def test_identical_build_is_idempotent_without_rewriting_frozen_files(tmp_path):
    s, bound = store(tmp_path), scope()
    first = build(s, bound, recipe(references=["rf-"+"1"*24]))
    folder = s.root / bound.key / "drafts" / first["draftId"]
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    again = build(s, bound, recipe(references=["rf-"+"2"*24]))
    assert first == again
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    assert len(s.list_build_drafts(bound)) == 1


@pytest.mark.parametrize("point", ["prestart", "before-publication", "after-publication", "release"])
def test_cancel_on_either_side_of_atomic_publication(tmp_path, monkeypatch, point):
    s, bound, cancel = store(tmp_path), scope(), threading.Event()
    published = []
    original = model_build_store.os.replace
    def replace(source, target):
        original(source, target)
        if target.parent.name == "drafts":
            published.append(target)
            if point == "after-publication":
                cancel.set()
    monkeypatch.setattr(model_build_store.os, "replace", replace)
    options = {}
    if point == "prestart":
        cancel.set()
    elif point == "before-publication":
        options["recheck"] = cancel.set
    elif point == "release":
        from ai_inspector.facility_layout.model_import_store import _Lease
        release = _Lease.release
        def cancelled_release(lease):
            release(lease)
            cancel.set()
        monkeypatch.setattr(_Lease, "release", cancelled_release)
    refused(lambda: build(s, bound, cancel=cancel, **options), "model_cancelled")
    rows = s.list_build_drafts(bound)
    assert len(rows) == (1 if point in ("after-publication", "release") else 0)
    if rows:
        assert s.draft(bound, rows[0]["draftId"])["kind"] == "build"
        assert s.preview(bound, rows[0]["draftId"], draft=True) == PNG
    assert s._active() == [] and not list((s.root / bound.key / "jobs").glob("*"))


def test_two_identical_builds_one_cancelled_only_its_job_is_removed(tmp_path):
    entered, proceed, cancel = threading.Barrier(2), threading.Event(), threading.Event()
    seen = []
    lock = threading.Lock()
    def worker(raw, destination, event, **kwargs):
        with lock:
            seen.append(destination.parent)
        entered.wait(timeout=10)
        if event is cancel:
            assert proceed.wait(10)
            cancel.set()
        result = write_build(raw, destination, event, **kwargs)
        if event is not cancel:
            proceed.set()
        return result
    s, bound = store(tmp_path, build_worker=worker), scope()
    with ThreadPoolExecutor(max_workers=2) as pool:
        cancelled = pool.submit(build, s, bound, cancel=cancel)
        good = pool.submit(build, s, bound)
        result = good.result(timeout=15)
        refused(lambda: cancelled.result(timeout=15), "model_cancelled")
    assert len(set(seen)) == 2 and all(not p.exists() for p in seen)
    assert [v["draftId"] for v in s.list_build_drafts(bound)] == [result["draftId"]]
    assert s._active() == []


def test_two_successful_identical_builds_publish_one_draft(tmp_path):
    gate = threading.Barrier(2)
    def worker(*args, **kwargs):
        value = write_build(*args, **kwargs)
        gate.wait(timeout=10)
        return value
    s, bound = store(tmp_path, build_worker=worker), scope()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(build, s, bound) for _ in range(2)]
        results = [f.result(timeout=15) for f in futures]
    assert results[0] == results[1]
    assert len(s.list_build_drafts(bound)) == 1


def test_interruption_after_publication_needs_no_parent_record_for_recovery(tmp_path, monkeypatch):
    s, bound = store(tmp_path), scope()
    class Interrupted(BaseException):
        pass
    original = s._resize
    def interrupted(lease, amount):
        if list((s.root / bound.key / "drafts").glob("md-*")):
            raise Interrupted()
        return original(lease, amount)
    monkeypatch.setattr(s, "_resize", interrupted)
    with pytest.raises(Interrupted):
        build(s, bound)
    fresh = store(tmp_path)
    fresh.reconcile()
    rows = fresh.list_build_drafts(bound)
    assert len(rows) == 1
    assert fresh.draft(bound, rows[0]["draftId"])["kind"] == "build"


def test_pending_job_uses_mbj_identity_and_failed_work_never_publishes(tmp_path):
    bound = scope()
    def worker(*args, **kwargs):
        active = s._active()
        assert len(active) == 1 and active[0]["kind"] == "build"
        assert active[0]["objectId"].startswith("mbj-") and len(active[0]["objectId"]) == 28
        assert "importId" not in active[0]
        raise ModelBuildError("schema_invalid", "$.entries[0]", "Generic refusal")
    s = store(tmp_path, build_worker=worker)
    with pytest.raises(FacilityLayoutError) as caught:
        build(s, bound)
    assert caught.value.code == "schema_invalid" and caught.value.details["path"] == "$.entries[0]"
    assert s.list_build_drafts(bound) == [] and s._active() == []


@pytest.mark.parametrize("boundary", ["build", "list", "draft", "parts", "preview", "receipt", "hold", "record"])
def test_scope_and_permissions_at_store_boundaries(tmp_path, boundary):
    s, owner = store(tmp_path), scope()
    made = build(s, owner)
    draft_id = made["draftId"]
    def call(bound):
        if boundary == "build":
            return build(s, bound)
        if boundary == "list":
            return s.list_build_drafts(bound)
        if boundary == "draft":
            return s.draft(bound, draft_id)
        if boundary == "parts":
            return s.draft_parts(bound, draft_id)
        if boundary == "preview":
            return s.preview(bound, draft_id, draft=True)
        if boundary == "receipt":
            return s.receipt(bound, draft_id)
        if boundary == "record":
            return s.record_receipt(bound, draft_id, s.draft(owner, draft_id)["assetId"], "revision")
        with s.hold_draft(bound, draft_id):
            return None
    if boundary in ("build", "record", "hold"):
        with pytest.raises(FacilityLayoutError):
            call(scope(role="viewer"))
    with pytest.raises(FacilityLayoutError):
        call(scope(layout="missing"))
    if boundary not in ("build", "list"):
        for other in (scope(site="b"), scope(tenant="other")):
            refused(lambda: call(other), "model_import_missing")
    else:
        assert s.list_build_drafts(scope(site="b")) == s.list_build_drafts(scope(tenant="other")) == []


def test_shared_capacity_and_user_admission_refuse_before_build_worker(tmp_path):
    def forbidden(*a, **kw):
        pytest.fail("No worker may run without capacity/admission")
    s = store(tmp_path, site_bytes=model_build_store.BUILD_RESERVATION-1, build_worker=forbidden)
    refused(lambda: build(s, scope()), "model_import_quota")
    s.site_bytes = 4*1024**3
    leases = []
    try:
        with disk.coordinator(s.root):
            leases.append(s._claim(scope(), "mi-"+"1"*24, 1024))
            leases.append(s._claim(scope(), "mbj-"+"2"*24, 1024, kind="build"))
        refused(lambda: build(s, scope()), "model_import_busy")
    finally:
        for lease in leases:
            lease.release()


def test_sweep_expiry_compaction_and_registration_lease(tmp_path):
    s, bound = store(tmp_path), scope()
    first = build(s, bound)
    value = s.draft(bound, first["draftId"])
    with s.hold_draft(bound, first["draftId"]) as (_, directory, lease):
        assert lease.data["kind"] == "build" and lease.data["objectId"] == first["draftId"]
        s.sweep(now=value["expires"]+1)
        assert directory.is_dir()
        s.record_receipt(bound, first["draftId"], value["assetId"], "revision", _lease=lease)
    s.sweep(now=value["expires"]+1)
    assert s.list_build_drafts(bound) == []
    assert {p.name for p in directory.iterdir()} == {"draft.json", "recipe.json", "result.json", "preview.png", "manifest.json"}
    assert s.draft(bound, first["draftId"]) == value
    second = build(s, bound, recipe(name="Other generic equipment"))
    s.sweep(now=time.time()+8*86400)
    refused(lambda: s.draft(bound, second["draftId"]), "model_import_missing")
    assert s.receipt(bound, first["draftId"])["assetId"] == value["assetId"]


def test_dead_build_job_recovery_preserves_published_output(tmp_path, monkeypatch):
    s, bound = store(tmp_path), scope()
    made = build(s, bound)
    with disk.coordinator(s.root):
        lease = s._claim(bound, "mbj-"+"3"*24, 1024, kind="build")
    try:
        monkeypatch.setattr(disk, "live", lambda value: False)
        s.reconcile()
        assert not lease.job.exists() and s._active() == []
        assert s.draft(bound, made["draftId"])["draftId"] == made["draftId"]
    finally:
        lease.release()


def test_twenty_unregistered_builds_per_site_including_held_drafts(tmp_path):
    s, bound = store(tmp_path), scope()
    first = build(s, bound, recipe(name="Generic item 0"))
    with s.hold_draft(bound, first["draftId"]):
        for i in range(1, 22):
            build(s, bound, recipe(name=f"Generic item {i}"))
        rows = s.list_build_drafts(bound)
        assert len(rows) == 20
        assert first["draftId"] in {v["draftId"] for v in rows}
        assert {v["name"] for v in rows} == {"Generic item 0", *(f"Generic item {i}" for i in range(3, 22))}


def test_eight_shared_app_reservations_prevent_a_ninth_build(tmp_path):
    s, bound = store(tmp_path, build_worker=lambda *a, **kw: pytest.fail("Admission failed")), scope()
    s._authorize(bound, True)
    leases = []
    try:
        with disk.coordinator(s.root):
            for i in range(8):
                leases.append(s._claim(scope(user=f"user-{i}"), f"mbj-{i:024x}", 1024, kind="build"))
        refused(lambda: build(s, bound), "model_import_busy")
    finally:
        for lease in leases:
            lease.release()


def test_legacy_import_draft_and_records_are_not_migrated_by_builds(tmp_path):
    s, bound = store(tmp_path), scope()
    record = upload(s, bound)
    imported = s.prepare(bound, import_recipe(record["id"]))
    folder = s.root / bound.key / "drafts" / imported["draftId"]
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    assert "kind" not in json.loads(before["draft.json"])
    build(s, bound)
    s.reconcile()
    s.sweep()
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    assert s.draft_parts(bound, imported["draftId"])["parts"] == imported["parts"]


@pytest.mark.parametrize("file", ["draft.json", "recipe.json", "result.json", "model.glb", "preview.png", "thumbnail.webp"])
def test_frozen_draft_tampering_is_refused(tmp_path, file):
    s, bound = store(tmp_path), scope()
    made = build(s, bound)
    target = s.root / bound.key / "drafts" / made["draftId"] / file
    target.write_bytes(target.read_bytes()+b" ")
    refused(lambda: s.draft(bound, made["draftId"]), "model_store_invalid")
