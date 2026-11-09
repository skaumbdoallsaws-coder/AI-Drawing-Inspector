"""Pre-worker failures must free admission without nesting the OS coordinator."""
from contextlib import contextmanager
import errno
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout import model_import_store as module
from ai_inspector.facility_layout import model_import_files as disk
from tests.model_import_store_support import store, scope, upload, recipe, wait


@contextmanager
def trace_leases(monkeypatch, instance):
    trace = SimpleNamespace(claimed=[], released=[], depth=0)
    claim, release, coordinator = instance._claim, module._Lease.release, disk.coordinator

    def claimed(*args, **kwargs):
        lease = claim(*args, **kwargs)
        trace.claimed.append(lease)
        return lease

    def released(lease):
        assert trace.depth == 0, "Lease release must leave the coordinator first"
        trace.released.append(lease.token)
        return release(lease)

    @contextmanager
    def coordinated(root):
        assert trace.depth == 0, "The OS coordinator is not recursive"
        with coordinator(root):
            trace.depth += 1
            try:
                yield
            finally:
                trace.depth -= 1

    with monkeypatch.context() as patch:
        patch.setattr(instance, "_claim", claimed)
        patch.setattr(module._Lease, "release", released)
        patch.setattr(disk, "coordinator", coordinated)
        yield trace


def assert_free(instance, trace=None):
    assert instance._active() == []
    folder = instance.root / scope().key
    assert not list((folder / "locks").glob("*.json"))
    assert not list((folder / "jobs").glob("*"))
    assert not list((folder / "uploads").glob("*.part"))
    assert not any(root == str(instance.root) for root, _ in module._OPERATIONS)
    if trace is not None:
        assert len(trace.claimed) == 1
        assert trace.released == [trace.claimed[0].token]
        assert trace.claimed[0].done.is_set()


def assert_admission_usable(instance):
    pending = [instance.begin_upload(scope(), "next.glb", 1) for _ in range(2)]
    for incoming in pending:
        incoming.abort()
    assert_free(instance)


@pytest.mark.parametrize("operation", ["prepare", "retry"])
@pytest.mark.parametrize("failure", ["before", "after", "persistent", "interrupt"])
def test_state_write_failure_releases_claim_before_worker_handoff(tmp_path, monkeypatch, operation, failure):
    instance = store(tmp_path)
    record = upload(instance)
    if operation == "retry":
        record["state"] = "failed"
        with disk.coordinator(instance.root):
            instance._save(scope(), record)
    saved = instance._save
    calls, fired = [], False

    class Interrupt(BaseException):
        pass

    def broken(bound, value):
        nonlocal fired
        if not fired and value["state"] == ("checking" if operation == "prepare" else "queued"):
            fired = True
            if failure == "after":
                saved(bound, value)
            if failure == "interrupt":
                raise Interrupt()
            raise OSError(errno.ENOSPC, "injected state-write failure")
        if failure == "persistent" and fired:
            raise OSError(errno.ENOSPC, "injected ongoing disk failure")
        saved(bound, value)

    with trace_leases(monkeypatch, instance) as trace:
        with monkeypatch.context() as patch:
            patch.setattr(instance, "_save", broken)
            patch.setattr(instance, "_start_inspect", lambda *a: calls.append("inspect"))
            patch.setattr(instance, "prepare_worker", lambda *a, **kw: calls.append("prepare"))
            expected = Interrupt if failure == "interrupt" else FacilityLayoutError
            with pytest.raises(expected) as caught:
                if operation == "prepare":
                    instance.prepare(scope(), recipe(record["id"]))
                else:
                    instance.retry(scope(), record["id"])
            if failure != "interrupt":
                assert caught.value.code == "model_import_quota" and caught.value.status_code == 507
        assert fired and calls == []
        assert_free(instance, trace)
        # Inspect disk before reconciliation: no orphan running/checking state.
        assert instance._record(scope(), record["id"])["state"] == ("ready" if operation == "prepare" else "failed")
        instance.reconcile()
    assert_admission_usable(instance)
    if operation == "prepare":
        assert instance.prepare(scope(), recipe(record["id"]))["draftId"].startswith("md-")
    else:
        queued = instance.retry(scope(), record["id"])
        assert wait(instance, scope(), queued["id"])["state"] == "ready"
    instance.close()


@pytest.mark.parametrize("failure", ["record", "name", "open"])
def test_initial_upload_failure_cleans_claim_and_any_record(tmp_path, monkeypatch, failure):
    instance = store(tmp_path)
    original_save, original_open = instance._save, Path.open
    fired = False

    def broken_save(bound, record):
        nonlocal fired
        if not fired:
            fired = True
            original_save(bound, record)  # Also protect errors after atomic publication.
            raise OSError(errno.ENOSPC, "injected")
        return original_save(bound, record)

    def broken_open(path, *args, **kwargs):
        if path.suffix == ".part":
            raise OSError(errno.ENOSPC, "injected upload stream open")
        return original_open(path, *args, **kwargs)

    def broken_name(_):
        raise OSError(errno.ENOSPC, "injected record construction")

    with trace_leases(monkeypatch, instance) as trace:
        with monkeypatch.context() as patch:
            if failure == "record":
                patch.setattr(instance, "_save", broken_save)
            elif failure == "name":
                patch.setattr(module, "clean_source_name", broken_name)
            else:
                patch.setattr(Path, "open", broken_open)
            with pytest.raises(FacilityLayoutError) as caught:
                instance.begin_upload(scope(), "x.glb", 1)
            assert caught.value.code == "model_import_quota"
        assert_free(instance, trace)
        for file in (instance.root / scope().key / "imports").glob("*.json"):
            assert disk.read_json(file)["state"] == "failed"
    assert_admission_usable(instance)


@pytest.mark.parametrize("operation", ["upload", "retry"])
@pytest.mark.parametrize("failure", ["construct", "start", "error_write"])
def test_thread_handoff_failure_always_releases_even_if_failure_record_cannot_be_written(
        tmp_path, monkeypatch, operation, failure):
    instance = store(tmp_path)
    incoming = None
    if operation == "retry":
        record = upload(instance)
        record["state"] = "failed"
        with disk.coordinator(instance.root):
            instance._save(scope(), record)
    original_save = instance._save

    def no_thread(*args, **kwargs):
        raise RuntimeError("injected thread creation failure")

    def no_start(_):
        raise RuntimeError("injected thread start failure")

    def no_failure_write(bound, value):
        if value["state"] == "failed":
            raise OSError(errno.ENOSPC, "cannot write failure")
        original_save(bound, value)

    with trace_leases(monkeypatch, instance) as trace:
        with monkeypatch.context() as patch:
            if operation == "upload":
                incoming = instance.begin_upload(scope(), "x.glb", 11)
                incoming.write(b"glTFfixture")
                import_id = incoming.lease.import_id
            else:
                import_id = record["id"]
            if failure == "construct":
                patch.setattr(module.threading, "Thread", no_thread)
            else:
                patch.setattr(module.threading.Thread, "start", no_start)
            if failure == "error_write":
                patch.setattr(instance, "_save", no_failure_write)
            with pytest.raises(FacilityLayoutError) as caught:
                incoming.finish() if incoming is not None else instance.retry(scope(), import_id)
            assert caught.value.code == "model_worker_failed"
        assert_free(instance, trace)
        # If the disk rejected the terminal write too, reconcile after storage
        # recovers; it must not wait for a live operation with no worker.
        instance.reconcile()
        assert instance._record(scope(), import_id)["state"] == "failed"
    assert_admission_usable(instance)
    assert wait(instance, scope(), instance.retry(scope(), import_id)["id"])["state"] == "ready"
    instance.close()


def test_registration_lease_failure_before_yield_releases_outside_coordinator(tmp_path, monkeypatch):
    instance = store(tmp_path)
    record = upload(instance)
    draft = instance.prepare(scope(), recipe(record["id"]))
    original_folder = instance._folder
    with trace_leases(monkeypatch, instance) as trace:
        fired = False

        def no_directory(bound):
            nonlocal fired
            if trace.claimed and not fired:
                fired = True
                raise OSError(errno.ENOSPC, "injected post-claim draft path failure")
            return original_folder(bound)

        with monkeypatch.context() as patch:
            patch.setattr(instance, "_folder", no_directory)
            with pytest.raises(OSError):
                with instance.hold_draft(scope(), draft["draftId"]):
                    pytest.fail("The registration body cannot own this lease yet")
        assert fired
        assert_free(instance, trace)
        assert instance._record(scope(), record["id"])["state"] == "ready"
    assert_admission_usable(instance)


@pytest.mark.parametrize("stage", ["active", "lock", "job"])
def test_partial_claim_failure_rolls_back_its_files_and_in_memory_owner(tmp_path, monkeypatch, stage):
    instance = store(tmp_path)
    atomic, mkdir = disk.atomic, disk.mkdir
    fired = False

    def failed_atomic(path, value):
        nonlocal fired
        atomic(path, value)
        if not fired and path.parent.name == ("active" if stage == "active" else "locks"):
            fired = True
            raise OSError(errno.ENOSPC, "injected after lease-marker write")

    def failed_mkdir(path):
        nonlocal fired
        result = mkdir(path)
        if not fired and path.parent.name == "jobs":
            fired = True
            raise OSError(errno.ENOSPC, "injected after job mkdir")
        return result

    with monkeypatch.context() as patch:
        if stage == "job":
            patch.setattr(disk, "mkdir", failed_mkdir)
        else:
            patch.setattr(disk, "atomic", failed_atomic)
        with pytest.raises(FacilityLayoutError) as caught:
            instance.begin_upload(scope(), "x", 1)
        assert caught.value.code == "model_import_quota"
    assert fired
    assert_free(instance)
    assert_admission_usable(instance)


@pytest.mark.parametrize("failure", ["flush", "fsync"])
def test_upload_flush_failure_and_close_failure_cannot_skip_release(tmp_path, monkeypatch, failure):
    instance = store(tmp_path)
    with trace_leases(monkeypatch, instance) as trace:
        incoming = instance.begin_upload(scope(), "x.glb", 11)
        incoming.write(b"glTFfixture")
        stream = incoming.stream

        def broken_flush():
            raise OSError(errno.ENOSPC, "cannot flush")

        def broken_close():
            stream.close()
            raise OSError(errno.EIO, "close also failed")

        with monkeypatch.context() as patch:
            incoming.stream = SimpleNamespace(flush=broken_flush if failure == "flush" else stream.flush,
                                               fileno=stream.fileno, close=broken_close)
            if failure == "fsync":
                patch.setattr(module.os, "fsync", lambda _: (_ for _ in ()).throw(OSError(errno.ENOSPC, "fsync failed")))
            with pytest.raises(FacilityLayoutError) as caught:
                incoming.finish()
            assert caught.value.code == "model_import_quota"
        assert stream.closed
        assert_free(instance, trace)
        # fsync was also unavailable for the attempted terminal record; reconcile
        # after storage recovers, with no abandoned live lease blocking it.
        instance.reconcile()
        assert instance._record(scope(), incoming.lease.import_id)["state"] == "failed"
    assert_admission_usable(instance)


def test_failed_partial_claim_cleanup_is_retried_without_waiting_for_a_worker(tmp_path, monkeypatch):
    instance = store(tmp_path)
    mkdir, remove = disk.mkdir, disk.remove

    def broken_mkdir(path):
        result = mkdir(path)
        if path.parent.name == "jobs":
            raise OSError(errno.ENOSPC, "after job mkdir")
        return result

    def broken_remove(path):
        if path.parent.name == "jobs":
            raise OSError(errno.EACCES, "transient cleanup failure")
        return remove(path)

    with monkeypatch.context() as patch:
        patch.setattr(disk, "mkdir", broken_mkdir)
        patch.setattr(disk, "remove", broken_remove)
        with pytest.raises(FacilityLayoutError) as caught:
            instance.begin_upload(scope(), "x", 1)
        assert caught.value.code == "model_import_quota"
    pending = [op for (root, _), op in module._OPERATIONS.items() if root == str(instance.root)]
    assert len(pending) == 1 and pending[0].ending
    original_wait = pending[0].done.wait

    def only_wait_after_cleanup(timeout=None):
        assert pending[0].done.is_set(), "Reconciliation must clean ending work before waiting"
        return original_wait(timeout)

    monkeypatch.setattr(pending[0].done, "wait", only_wait_after_cleanup)
    instance.reconcile()
    assert_free(instance)
    assert_admission_usable(instance)
