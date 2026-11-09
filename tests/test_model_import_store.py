"""MI1 scope, capacity, durable lifecycle and retention tests on temporary roots."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

import pytest

from ai_inspector.facility_layout import model_import_files as disk
from ai_inspector.facility_layout import model_import_store as module
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.industrial_assets.model_import.errors import ModelImportError
from tests.model_import_store_support import (inspect_worker, prepare_worker, recipe, scope, store, upload, wait)


def refusal(call, code, status=None):
    with pytest.raises(FacilityLayoutError) as caught:
        call()
    assert caught.value.code == code
    if status:
        assert caught.value.status_code == status
    return caught.value


def age(store, bound, import_id, **updates):
    with disk.coordinator(store.root):
        record = store._record(bound, import_id)
        record.update(updates)
        store._save(bound, record)


def test_upload_returns_queued_then_ready_and_pages_without_geometry(tmp_path):
    instance = store(tmp_path, inspect_worker=lambda *a, **kw: inspect_worker(*a, **kw, count=80))
    incoming = instance.begin_upload(scope(), "../../A\x00 Model.glb", 7)
    incoming.write(b"glTF")
    incoming.write(b"abc")
    queued = incoming.finish()
    assert queued["state"] == "queued" and queued["name"] == "A Model.glb"
    record = wait(instance, scope(), queued["id"])
    assert record["state"] == "ready" and record["licence"]["class"] == "cc0"
    assert record["bytes"] == 7 and record["createdBy"] == "u"
    page = instance.inspect(scope(), record["id"], 64, 16)
    assert len(page["parts"]) == 16 and page["parts"][0]["key"] == "p64" and page["nextPartsOffset"] is None
    assert not list(instance.root.rglob("*.npz"))
    assert instance.preview(scope(), record["id"]).startswith(b"\x89PNG")


def test_permissions_layout_and_tenant_site_scope_on_every_lookup(tmp_path):
    instance = store(tmp_path)
    refusal(lambda: instance.begin_upload(scope(role="viewer"), "x", 1), "role_not_authorized", 403)
    refusal(lambda: instance.begin_upload(scope(layout="missing"), "x", 1), "not_found", 404)
    record = upload(instance)
    draft = instance.prepare(scope(), recipe(record["id"]))
    for foreign in (scope(site="b"), scope(tenant="other")):
        for action in (lambda: instance.get(foreign, record["id"]),
                       lambda: instance.inspect(foreign, record["id"]),
                       lambda: instance.preview(foreign, record["id"]),
                       lambda: instance.retry(foreign, record["id"]),
                       lambda: instance.prepare(foreign, recipe(record["id"])),
                       lambda: instance.draft(foreign, draft["draftId"]),
                       lambda: instance.draft_parts(foreign, draft["draftId"]),
                       lambda: instance.receipt(foreign, draft["draftId"]),
                       lambda: instance.preview(foreign, draft["draftId"], draft=True)):
            refusal(action, "model_import_missing", 404)
    refusal(lambda: instance.prepare(scope(role="viewer"), recipe(record["id"])), "role_not_authorized", 403)
    refusal(lambda: instance.retry(scope(role="viewer"), record["id"]), "role_not_authorized", 403)
    refusal(lambda: instance.record_receipt(scope(role="viewer"), draft["draftId"], "x", "y"), "role_not_authorized", 403)
    assert instance.get(scope(role="viewer"), record["id"])["state"] == "ready"


def test_body_cap_and_invalid_content_lengths_precede_worker(tmp_path, monkeypatch):
    instance = store(tmp_path)
    refusal(lambda: instance.begin_upload(scope(), "x", module.MAX_UPLOAD_BYTES + 1), "model_too_large", 413)
    refusal(lambda: instance.begin_upload(scope(), "x", -1), "model_upload_length", 400)
    incoming = instance.begin_upload(scope(), "x", 1)
    monkeypatch.setattr(module, "MAX_UPLOAD_BYTES", 4)
    refusal(lambda: incoming.write(b"12345"), "model_too_large", 413)
    incoming.abort()
    assert not instance._active()


def test_admission_is_atomic_two_per_user_eight_per_app(tmp_path):
    instance = store(tmp_path)
    held = [instance.begin_upload(scope(), "x", 1) for _ in range(2)]
    refusal(lambda: instance.begin_upload(scope(), "x", 1), "model_import_busy", 429)
    held += [instance.begin_upload(scope(user=f"u{i}"), "x", 1) for i in range(6)]
    refusal(lambda: instance.begin_upload(scope(user="other"), "x", 1), "model_import_busy", 429)
    for incoming in held:
        incoming.abort()
    assert instance._active() == []


def test_concurrent_reservations_across_store_instances_do_not_overbook(tmp_path):
    first = store(tmp_path, site_bytes=module.MAX_UPLOAD_BYTES + module.MARGIN + 10000)
    second = store(tmp_path, site_bytes=first.site_bytes)
    barrier = threading.Barrier(2)
    def begin(instance, user):
        barrier.wait()
        try:
            return instance.begin_upload(scope(user=user), "x")  # Header-less: reserve 128 MiB.
        except FacilityLayoutError as error:
            return error
    with ThreadPoolExecutor(2) as pool:
        a, b = pool.submit(begin, first, "a"), pool.submit(begin, second, "b")
        results = [a.result(), b.result()]
    assert sum(isinstance(x, module.Upload) for x in results) == 1
    assert [x.code for x in results if isinstance(x, FacilityLayoutError)] == ["model_import_quota"]
    for result in results:
        if isinstance(result, module.Upload):
            result.abort()


def test_headerless_and_dishonest_length_reserve_before_writing(tmp_path):
    instance = store(tmp_path, site_bytes=module.MARGIN + 10000)
    refusal(lambda: instance.begin_upload(scope(), "x"), "model_import_quota", 507)
    incoming = instance.begin_upload(scope(), "x", 1)
    before = incoming.path.stat().st_size
    refusal(lambda: incoming.write(b"x" * 20000), "model_import_quota", 507)
    assert incoming.path.stat().st_size == before
    incoming.abort()


def test_large_job_reserves_input_and_bounded_outputs_before_worker(tmp_path):
    calls = []
    instance = store(tmp_path, site_bytes=module.INSPECT_OUTPUT_BYTES + 10000,
                     inspect_worker=lambda *a, **kw: calls.append(1))
    incoming = instance.begin_upload(scope(), "x", 20000)
    incoming.write(b"x" * 20000)
    record = wait(instance, scope(), incoming.finish()["id"])
    assert record["state"] == "failed" and record["refusal"]["code"] == "model_import_quota"
    assert calls == [] and not instance._active()


@pytest.mark.parametrize("error,state", [(ModelImportError("gltf_invalid"), "refused"),
    (ModelImportError("model_timeout"), "failed"), (RuntimeError("crash"), "failed"),
    (ModelImportError("model_limits_unavailable"), "failed")])
def test_worker_refusal_timeout_and_crash_leave_pollable_records(tmp_path, error, state):
    def broken(*args, **kwargs):
        raise error
    instance = store(tmp_path, inspect_worker=broken)
    record = upload(instance)
    assert record["state"] == state and record["refusal"]["code"] == getattr(error, "code", "model_worker_failed")
    assert instance.get(scope(), record["id"])["refusal"] == record["refusal"]
    assert not instance._active() and not list((instance.root / scope().key / "jobs").iterdir())


def test_duplicate_source_refcounts_and_failed_record_sweep(tmp_path):
    instance = store(tmp_path)
    first, second = upload(instance), upload(instance, name="copy.zip")
    sources = instance.root / scope().key / "sources"
    assert first["id"] != second["id"] and first["sha256"] == second["sha256"] and len(list(sources.iterdir())) == 1
    for record in (first, second):
        age(instance, scope(), record["id"], state="failed", updated=time.time() - 2 * module.DAY)
        instance.sweep()
        assert len(list(sources.iterdir())) == (1 if record is first else 0)


def abandon(instance, incoming, monkeypatch):
    incoming.stream.close()
    incoming.finished = True
    lease = incoming.lease
    with module._OPERATIONS_LOCK:
        module._OPERATIONS.pop((str(instance.root), lease.token))
    lease.data.update(pid=987654321, processStart="dead")
    disk.atomic(instance.root / "active" / (lease.token + ".json"), lease.data)
    disk.atomic(instance.root / scope().key / "locks" / (lease.import_id + ".json"), lease.data)
    original = disk.process_start
    monkeypatch.setattr(disk, "process_start", lambda pid: None if pid == 987654321 else original(pid))


def test_restart_during_upload_removes_partial_and_marks_failed(tmp_path, monkeypatch):
    instance = store(tmp_path)
    incoming = instance.begin_upload(scope(), "x", 8)
    incoming.write(b"half")
    abandon(instance, incoming, monkeypatch)
    restarted = store(tmp_path)
    record = restarted.get(scope(), incoming.lease.import_id)
    assert record["state"] == "failed" and record["refusal"]["code"] == "interrupted"
    assert not incoming.path.exists() and restarted._active() == []
    refusal(lambda: restarted.retry(scope(), record["id"]), "model_import_missing", 404)


@pytest.mark.parametrize("state", ["queued", "checking"])
def test_restart_during_worker_or_result_publication_is_retryable(tmp_path, monkeypatch, state):
    instance = store(tmp_path)
    leases = []
    monkeypatch.setattr(instance, "_start_inspect", lambda lease: leases.append(lease))
    incoming = instance.begin_upload(scope(), "x", 4)
    incoming.write(b"glTF")
    record = incoming.finish()
    age(instance, scope(), record["id"], state=state)
    (leases[0].job / "partial").write_bytes(b"incomplete")
    # The upload was published, but no actual thread was started.
    incoming.finished = False
    abandon(instance, incoming, monkeypatch)
    restarted = store(tmp_path)
    failed = restarted.get(scope(), record["id"])
    assert failed["state"] == "failed" and failed["refusal"]["code"] == "interrupted"
    retried = restarted.retry(scope(), record["id"])
    assert retried["state"] == "queued" and wait(restarted, scope(), record["id"])["state"] == "ready"


def test_sweep_never_reclaims_old_live_foreign_lock(tmp_path):
    instance = store(tmp_path)
    incoming = instance.begin_upload(scope(), "x", 3)
    incoming.write(b"abc")
    lease = incoming.lease
    disk.atomic(instance.root / scope().key / "locks" / (lease.import_id + ".json"),
                {**lease.data, "created": time.time() - 10000})
    # No local callback for a foreign process: matching PID/start is live regardless of age.
    instance.sweep(now=time.time() + 20 * module.DAY)
    assert incoming.path.exists() and instance.get(scope(), lease.import_id)["state"] == "queued"
    incoming.abort()


def test_old_local_worker_is_cancelled_and_joined_before_sweep(tmp_path):
    entered = threading.Event()
    def waiting(job, dependencies, *, cancel_event):
        entered.set()
        assert cancel_event.wait(5)
        assert job.exists(), "sweep must wait for worker termination"
        raise ModelImportError("model_cancelled")
    instance = store(tmp_path, inspect_worker=waiting)
    incoming = instance.begin_upload(scope(), "x", 1)
    incoming.write(b"x")
    record = incoming.finish()
    assert entered.wait(2)
    incoming.lease.data["created"] = time.time() - module.STALE_SECONDS - 1
    instance.sweep()
    assert incoming.lease.done.is_set() and not incoming.lease.job.exists()
    assert instance.get(scope(), record["id"])["state"] == "failed"


def test_twenty_unregistered_drafts_and_seven_day_expiry(tmp_path):
    instance = store(tmp_path)
    record = upload(instance)
    values = [instance.prepare(scope(), recipe(record["id"], changesNote=str(i))) for i in range(22)]
    kept = instance.get(scope(), record["id"])["drafts"]
    assert len(kept) == 20
    refusal(lambda: instance.draft(scope(), values[0]["draftId"]), "model_import_missing", 404)
    assert instance.prepare(scope(), recipe(record["id"], changesNote="21")) == values[-1]
    instance.sweep(now=time.time() + 8 * module.DAY)
    assert instance.get(scope(), record["id"])["drafts"] == []


def test_registered_draft_keeps_metadata_paging_preview_after_restart(tmp_path):
    instance = store(tmp_path)
    record = upload(instance)
    draft = instance.prepare(scope(), recipe(record["id"]))
    asset_id = "asset-import-fixture-" + "a" * 24
    with instance.hold_draft(scope(), draft["draftId"]) as (frozen, folder, lease):
        receipt = instance.record_receipt(scope(), draft["draftId"], asset_id, "rev", _lease=lease)
        assert not (folder / "model.glb").exists()
        assert (folder / "draft.json").is_file() and (folder / "parts.jsonl").is_file()
    restarted = store(tmp_path)
    restarted.sweep(now=time.time() + 100 * module.DAY)
    assert restarted.record_receipt(scope(), draft["draftId"], asset_id, "rev") == receipt
    assert restarted.draft_parts(scope(), draft["draftId"])["partsTotal"] == 1
    assert restarted.preview(scope(), draft["draftId"], draft=True).startswith(b"\x89PNG")
    assert restarted.get(scope(), record["id"])["registrations"] == [receipt]
    refusal(lambda: restarted.record_receipt(scope(), draft["draftId"], asset_id, "changed"), "asset_identity_conflict")


def test_prepare_cancel_releases_slot_lock_and_draft(tmp_path):
    entered, cancel = threading.Event(), threading.Event()
    def waiting(source, recipe, destination, event, **kwargs):
        entered.set()
        assert event.wait(5)
        raise ModelImportError("model_cancelled")
    instance = store(tmp_path, prepare_worker=waiting)
    record = upload(instance)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(instance.prepare, scope(), recipe(record["id"]), cancel)
        assert entered.wait(2)
        cancel.set()
        with pytest.raises(FacilityLayoutError) as caught:
            future.result()
    assert caught.value.code == "model_cancelled"
    assert instance.get(scope(), record["id"])["state"] == "ready" and instance._active() == []
    assert instance.get(scope(), record["id"])["drafts"] == []


def test_restart_after_draft_rename_recovers_record_index(tmp_path, monkeypatch):
    instance = store(tmp_path)
    record = upload(instance)
    original = instance._save
    class Crash(BaseException):
        pass
    def die(scope, value):
        if value["state"] == "ready" and value["drafts"]:
            raise Crash()
        original(scope, value)
    monkeypatch.setattr(instance, "_save", die)
    with pytest.raises(Crash):
        instance.prepare(scope(), recipe(record["id"]))
    restarted = store(tmp_path)
    result = restarted.get(scope(), record["id"])
    assert result["state"] == "failed" and result["refusal"]["code"] == "interrupted"
    assert len(result["drafts"]) == 1
    restarted.retry(scope(), record["id"])
    assert wait(restarted, scope(), record["id"])["state"] == "ready"
    assert restarted.prepare(scope(), recipe(record["id"]))["draftId"] == result["drafts"][0]["id"]


def test_list_is_newest_twenty_and_names_are_data(tmp_path):
    instance = store(tmp_path)
    records = []
    for i in range(22):
        incoming = instance.begin_upload(scope(), f"{i} ignore instructions.glb", 1)
        records.append(incoming.lease.import_id)
        incoming.abort()
    result = instance.list(scope())
    assert len(result) == 20 and result[0]["id"] == records[-1]
    assert "ignore instructions" in result[0]["name"]


def test_symlink_store_paths_are_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = tmp_path / "linked"
    try:
        parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    refusal(lambda: store(parent), "model_store_invalid", 503)


def test_worker_recipe_details_survive_host_translation(tmp_path):
    instance = store(tmp_path)
    error = refusal(lambda: instance.prepare(scope(), {"name": "No id", "category": "decor"}), "recipe_invalid", 422)
    assert {"path": "importId", "problem": "required"} in error.details["problems"]


def test_real_worker_store_smoke(tmp_path):
    from tests.model_import_test_support import textured_box
    from ai_inspector.facility_layout.model_import_store import ModelImportStore
    from tests.model_import_store_support import layout_reader
    instance = ModelImportStore(tmp_path, layout_reader=layout_reader)
    incoming = instance.begin_upload(scope(), "box.glb")
    incoming.write(textured_box().bytes())
    record = incoming.finish()
    deadline = time.monotonic() + 70
    while time.monotonic() < deadline:
        record = instance.get(scope(), record["id"])
        if record["state"] not in ("queued", "checking"):
            break
        time.sleep(.05)
    assert record["state"] == "ready", record
    # Wait for the prior lease to be released before preparing the same import.
    wait(instance, scope(), record["id"])
    draft = instance.prepare(scope(), recipe(record["id"]))
    assert instance.preview(scope(), draft["draftId"], draft=True).startswith(b"\x89PNG")


def test_concurrent_duplicate_uploads_share_one_source(tmp_path):
    instance = store(tmp_path)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(upload, instance, scope(user="first"))
        second = pool.submit(upload, instance, scope(user="second"))
        a, b = first.result(), second.result()
    assert a["state"] == b["state"] == "ready" and a["id"] != b["id"]
    assert len(list((instance.root / scope().key / "sources").iterdir())) == 1


def test_repeated_prepare_settles_actual_bytes_and_refuses_before_next_worker(tmp_path):
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return prepare_worker(*args, **kwargs)
    instance = store(tmp_path, prepare_worker=counted)
    record = upload(instance)
    instance.site_bytes = disk.size(instance.root / scope().key) + record["bytes"] + module.PREPARE_OUTPUT_BYTES + 1024
    first = instance.prepare(scope(), recipe(record["id"]))
    refusal(lambda: instance.prepare(scope(), recipe(record["id"], changesNote="new")), "model_import_quota", 507)
    assert calls == [1] and instance._active() == []
    assert instance.prepare(scope(), recipe(record["id"])) == first


def test_receipt_written_before_cleanup_failure_is_recoverable(tmp_path, monkeypatch):
    instance = store(tmp_path)
    record = upload(instance)
    draft = instance.prepare(scope(), recipe(record["id"]))
    def interrupted(*args):
        raise OSError("crashed after receipt")
    monkeypatch.setattr(instance, "_compact", interrupted)
    asset = "asset-import-fixture-" + "b" * 24
    refusal(lambda: instance.record_receipt(scope(), draft["draftId"], asset, "rev"), "model_store_unavailable", 503)
    restarted = store(tmp_path)
    assert restarted.record_receipt(scope(), draft["draftId"], asset, "rev")["assetId"] == asset
    assert restarted.preview(scope(), draft["draftId"], draft=True).startswith(b"\x89PNG")


def test_live_reservation_is_counted_without_racy_owned_size_subtraction(tmp_path, monkeypatch):
    instance = store(tmp_path, site_bytes=module.MAX_UPLOAD_BYTES + module.MARGIN + 10000)
    incoming = instance.begin_upload(scope(), "x")
    monkeypatch.setattr(instance, "_owned_size", lambda value: module.SITE_BYTES)
    # An increasing job size cannot make the second reservation appear to fit.
    refusal(lambda: instance.begin_upload(scope(user="other"), "x"), "model_import_quota", 507)
    incoming.abort()


def test_cancel_after_rename_preserves_existing_drafts_and_removes_new_one(tmp_path, monkeypatch):
    instance = store(tmp_path)
    record = upload(instance)
    old = instance.prepare(scope(), recipe(record["id"]))
    cancel = threading.Event()
    original = module.os.replace
    def replace_and_cancel(source, target):
        result = original(source, target)
        if Path(target).parent.name == "drafts":
            cancel.set()
        return result
    monkeypatch.setattr(module.os, "replace", replace_and_cancel)
    refusal(lambda: instance.prepare(scope(), recipe(record["id"], changesNote="new"), cancel), "model_cancelled")
    assert instance.draft(scope(), old["draftId"])["draftId"] == old["draftId"]
    assert len(instance.get(scope(), record["id"])["drafts"]) == 1
    assert instance._active() == []


def test_process_identity_reuse_and_corrupt_lock_are_not_age_checks(tmp_path):
    identity = disk.owner()
    assert disk.live(identity)
    assert not disk.live({**identity, "processStart": "an earlier process"})
    assert disk.live({}) and disk.live(None)


def test_cancel_during_final_cleanup_does_not_deliver_or_retain_new_draft(tmp_path, monkeypatch):
    instance = store(tmp_path)
    record = upload(instance)
    cancel = threading.Event()
    original = module._Lease.release
    def late(lease):
        original(lease)
        cancel.set()
    monkeypatch.setattr(module._Lease, "release", late)
    refusal(lambda: instance.prepare(scope(), recipe(record["id"]), cancel), "model_cancelled")
    assert instance.get(scope(), record["id"])["drafts"] == []


def test_cross_process_reservations_use_the_kernel_lock(tmp_path):
    import json
    import os
    import subprocess
    import sys
    child = tmp_path / "child.py"
    child.write_bytes(b"""import pathlib,sys,time,types,json
root,folder,user=pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2]),sys.argv[3]
sys.path.insert(0,str(root))
for name,relative in [('ai_inspector.facility_layout','ai_inspector/facility_layout'),('ai_inspector.industrial_assets','ai_inspector/industrial_assets')]:
 p=types.ModuleType(name);p.__path__=[str(root/relative)];sys.modules[name]=p
from tests.model_import_store_support import store,scope
from ai_inspector.facility_layout.model_import_store import MAX_UPLOAD_BYTES,MARGIN
from ai_inspector.facility_layout.errors import FacilityLayoutError
instance=store(folder/'data',site_bytes=MAX_UPLOAD_BYTES+MARGIN+10000)
while not (folder/'go').exists():time.sleep(.01)
incoming=None
try:
 incoming=instance.begin_upload(scope(user=user),'x')
 result={'held':True}
except FacilityLayoutError as e:result={'code':e.code}
(folder/(user+'.json')).write_bytes(json.dumps(result).encode())
while not (folder/'release').exists():time.sleep(.01)
if incoming:incoming.abort()
""")
    processes = []
    try:
        for user in ("one", "two"):
            processes.append(subprocess.Popen(
                [getattr(sys, "_base_executable", sys.executable), "-I", "-S", "-B", str(child),
                 str(Path(__file__).resolve().parents[1]), str(tmp_path), user],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        (tmp_path / "go").write_bytes(b"go")
        deadline = time.monotonic() + 10
        while not all((tmp_path / (u + ".json")).is_file() for u in ("one", "two")) and time.monotonic() < deadline:
            time.sleep(.02)
        results = [json.loads((tmp_path / (u + ".json")).read_bytes()) for u in ("one", "two")]
        assert results.count({"held": True}) == results.count({"code": "model_import_quota"}) == 1
        (tmp_path / "release").write_bytes(b"release")
        for process in processes:
            _, stderr = process.communicate(timeout=5)
            assert process.returncode == 0, stderr.decode(errors="replace")
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait()


def test_restart_after_source_preview_publication_reaches_terminal_and_retries(tmp_path, monkeypatch):
    import os
    instance = store(tmp_path)
    leases = []
    monkeypatch.setattr(instance, "_start_inspect", lambda lease: leases.append(lease))
    incoming = instance.begin_upload(scope(), "x", 4)
    incoming.write(b"glTF")
    record = incoming.finish()
    lease = leases[0]
    (lease.job / "source.bin").write_bytes(b"glTF")
    disk.atomic(lease.job / "request.json", {"name": "x", "storeMetadata": True})
    inspect_worker(lease.job, tmp_path, cancel_event=lease.cancel)
    directory = disk.mkdir(instance.root / scope().key / "inspections" / record["id"])
    for name in ("summary.json", "inspection.json", "preview.png"):
        os.replace(lease.job / name, directory / name)
    age(instance, scope(), record["id"], state="checking")
    incoming.finished = False
    abandon(instance, incoming, monkeypatch)
    restarted = store(tmp_path)
    failed = restarted.get(scope(), record["id"])
    assert failed["refusal"]["code"] == "interrupted"
    refusal(lambda: restarted.preview(scope(), record["id"]), "model_import_missing", 404)
    restarted.retry(scope(), record["id"])
    assert wait(restarted, scope(), record["id"])["state"] == "ready"


def test_unicode_draft_parts_page_stays_under_tool_budget(tmp_path):
    def many(*args, **kwargs):
        return prepare_worker(*args, **kwargs, count=64, part_name="\U0001f333" * 80)
    instance = store(tmp_path, prepare_worker=many)
    record = upload(instance)
    draft = instance.prepare(scope(), recipe(record["id"]))
    page = instance.draft_parts(scope(), draft["draftId"], 0, 64)
    assert 0 < len(page["parts"]) < 64 and len(disk.encode(page)) <= 48 * 1024
    tail = instance.draft_parts(scope(), draft["draftId"], page["nextPartsOffset"], 64)
    assert len(page["parts"]) + len(tail["parts"]) == 64


def test_tool_import_list_projects_only_bounded_listing_fields(tmp_path):
    instance = store(tmp_path)
    incoming = instance.begin_upload(scope(), "Name", 1)
    incoming.abort(FacilityLayoutError("example", "Refusal", details={"reason": "x" * 6000}))
    listing = instance.inspect(scope())
    assert set(listing["imports"][0]) == {"id", "importId", "name", "state", "created"}
    assert len(disk.encode(listing)) <= 48 * 1024


def test_exited_process_is_not_live_while_parent_keeps_its_handle():
    import os
    import subprocess
    import sys
    process = subprocess.Popen([getattr(sys, "_base_executable", sys.executable), "-I", "-S", "-B", "-c",
                                "import time;time.sleep(.3)"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        started = disk.process_start(process.pid)
        assert started not in (None, "?")
        process.wait(timeout=5)
        assert disk.process_start(process.pid) is None
        assert not disk.live({"pid": process.pid, "processStart": started})
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


@pytest.mark.parametrize("same_size", [False, True])
def test_changed_source_is_refused_before_copying_or_worker_launch(tmp_path, same_size):
    calls = []
    instance = store(tmp_path, prepare_worker=lambda *a, **k: calls.append(1))
    record = upload(instance)
    source = instance._source(scope(), record)
    source.write_bytes(b"x" * (record["bytes"] if same_size else record["bytes"] + 1))
    refusal(lambda: instance.prepare(scope(), recipe(record["id"])), "model_cache_invalid")
    assert calls == [] and instance._active() == []


def test_import_nonce_collision_does_not_overwrite_a_record(tmp_path, monkeypatch):
    from types import SimpleNamespace
    instance = store(tmp_path)
    record = upload(instance)
    original = instance.get(scope(), record["id"])
    monkeypatch.setattr(module.uuid, "uuid4", lambda: SimpleNamespace(hex=record["id"][3:] + "0" * 8))
    refusal(lambda: instance.begin_upload(scope(), "replacement", 1), "model_import_busy", 429)
    assert instance.get(scope(), record["id"]) == original
