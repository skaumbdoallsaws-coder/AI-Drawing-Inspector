"""Crash/fault contracts, temporary stores only; no product test hooks or expected failures.

The two-writer test deliberately synchronizes at the existing atomic-replace seam.
It must fail if a process-local lock lets both writers report success.
"""
from copy import deepcopy
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

import pytest

from ai_inspector.documentation import commands
from ai_inspector.parts_manual import documentation as persistence
from tests.documentation_recovery_support import (
    SceneHarness, NUMBER, SOURCE, PLAN, PAGE, seed, request_for, loaded, snapshot, assert_complete, export_document,
)

ROOT = Path(__file__).resolve().parents[1]
_CHILDREN = []


@pytest.fixture(autouse=True)
def reap_children():
    yield
    for process in _CHILDREN:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)
    _CHILDREN.clear()


@pytest.fixture
def store(tmp_path):
    return seed(tmp_path / "s")


def start(tmp_path, store, *, point=None, action="commit", request=None, **extra):
    control = tmp_path / ("c" + str(len(list(tmp_path.glob("c*")))))
    control.mkdir()
    (control / "input.json").write_text(json.dumps({"root": str(store.root), "action": action,
        "point": point, "request": request, **extra}), encoding="utf-8")
    log = (control / "child.log").open("wb")
    process = subprocess.Popen([sys.executable, "-m", "tests.documentation_recovery_support", str(control)],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log.close()
    _CHILDREN.append(process)
    return process, control


def wait_at(process, control):
    deadline = time.monotonic() + 15
    while not (control / "ready").exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(.01)
    if not (control / "ready").exists():
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        pytest.fail("Child never reached its named point: " + (control / "child.log").read_text(errors="replace"))


def finish(process, control, *, kill=False):
    if kill:
        process.kill()
    try:
        code = process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill(); process.wait(timeout=5)
        pytest.fail("Child did not exit: " + (control / "child.log").read_text(errors="replace"))
    if kill:
        assert code != 0
        return None
    result = control / "result.json"
    assert result.exists(), (control / "child.log").read_text(errors="replace")
    return json.loads(result.read_bytes())


def post_image(tmp_path, control):
    """Open the exact staged candidate through the public reader in a second store."""
    probe = SceneHarness(tmp_path / (control.name + "p"))
    probe.path.parent.mkdir(parents=True)
    probe.path.write_bytes((control / "candidate.json").read_bytes())
    return snapshot(probe)


def test_killed_before_replace_preserves_old_state_and_retry_applies_once(store, tmp_path):
    before = snapshot(store); request = request_for(store, {"title": "replacement"})
    process, control = start(tmp_path, store, point="before_replace", request=request)
    wait_at(process, control); after = post_image(tmp_path, control)
    finish(process, control, kill=True)
    assert list(store.path.parent.glob(".tmp-documentation-*")), "The killed writer left its staged file"
    assert assert_complete(store, before, after) == before
    # An abandoned .tmp file is not a scene. A new write ignores it.
    receipt = store.commit(request); committed = snapshot(store)
    assert store.commit(request) == receipt
    assert loaded(store)["scene"]["historyCursor"] == 2 and store.values()["title"] == "replacement"
    assert_complete(store, committed, committed)


def test_killed_after_replace_returns_retained_receipt_without_second_apply(store, tmp_path):
    before = snapshot(store); request = request_for(store, {"title": "replacement"})
    process, control = start(tmp_path, store, point="after_replace", request=request)
    wait_at(process, control); after = post_image(tmp_path, control)
    finish(process, control, kill=True)
    assert assert_complete(store, before, after) == after
    result = loaded(store); receipt = result["scene"]["receipts"][request["requestId"]]["receipt"]
    assert store.commit(request) == receipt
    assert loaded(store)["revision"] == result["revision"]
    assert loaded(store)["scene"]["historyCursor"] == 2
    assert_complete(store, before, after)


def test_killed_during_refresh_rebuild_preserves_complete_scene(store, tmp_path):
    before = snapshot(store)
    process, control = start(tmp_path, store, point="refresh_compile", action="refresh")
    wait_at(process, control); finish(process, control, kill=True)
    assert_complete(store, before, before)


@pytest.mark.parametrize("kind", ["pdf", "docx"])
@pytest.mark.parametrize("point", ["export_before_replace", "export_payload", "export_ready"])
def test_killed_export_cannot_advertise_incomplete_artifact_and_retry_succeeds(store, tmp_path, kind, point):
    from ai_inspector.operations_manual import exports
    before = snapshot(store); export_root = tmp_path / "e"
    process, control = start(tmp_path, store, point=point, action="export", kind=kind, exports=str(export_root))
    wait_at(process, control); finish(process, control, kill=True)
    metadata = list(export_root.rglob("review-" + kind + ".json"))
    if point != "export_ready":
        assert not metadata, "No ready metadata before its commit"
    for path in metadata:
        ready = json.loads(path.read_bytes())
        payload = path.with_name(ready["filename"]).read_bytes()
        assert ready["status"] == "ready" and ready["byteLength"] == len(payload)
        assert ready["sha256"] == hashlib.sha256(payload).hexdigest()
    result = getattr(exports, "store_prototype_" + kind)(export_root, NUMBER, export_document())
    artifact = next(export_root.rglob(result["filename"]))
    data = artifact.read_bytes()
    assert result["status"] == "ready" and result["byteLength"] == len(data)
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    if kind == "pdf":
        import fitz
        with fitz.open(stream=data, filetype="pdf") as pdf:
            assert pdf.page_count == 1 and "Recovery export complete" in pdf[0].get_text()
    else:
        with zipfile.ZipFile(artifact) as package:
            assert package.testzip() is None and b"Recovery export complete" in package.read("word/document.xml")
    assert_complete(store, before, before)


def legacy(store):
    value = json.loads(store.path.read_bytes()); value["schemaVersion"] = 7
    original = b"  " + json.dumps(value, indent=2).encode() + b"\n"
    store.path.write_bytes(original)
    return original


@pytest.mark.parametrize("migration,write_number", [(False, 1), (True, 1), (True, 2)])
@pytest.mark.parametrize("stage", ["create", "write", "flush", "fsync", "replace"])
def test_disk_full_at_each_commit_write_preserves_old_state(store, monkeypatch, migration, write_number, stage):
    if migration:
        legacy(store)
    before = snapshot(store); request = request_for(store, {"title": "disk full"})
    calls = {"writes": 0, "reached": False}
    original_writer = persistence._write_atomic
    def fault_writer(path, payload):
        calls["writes"] += 1
        if calls["writes"] != write_number:
            return original_writer(path, payload)
        def fail(*args, **kwargs):
            calls["reached"] = True
            raise OSError(errno.ENOSPC, "No space left on device")
        with monkeypatch.context() as patch:
            if stage == "create":
                patch.setattr(persistence.tempfile, "mkstemp", fail)
            elif stage in {"fsync", "replace"}:
                patch.setattr(persistence.os, stage, fail)
            else:
                fdopen = persistence.os.fdopen
                class Writer:
                    def __init__(self, *args, **kwargs): self.handle = fdopen(*args, **kwargs)
                    def __enter__(self): return self
                    def __exit__(self, *args): return self.handle.__exit__(*args)
                    def write(self, value): return fail() if stage == "write" else self.handle.write(value)
                    def flush(self): return fail() if stage == "flush" else self.handle.flush()
                    def fileno(self): return self.handle.fileno()
                patch.setattr(persistence.os, "fdopen", Writer)
            return original_writer(path, payload)
    with monkeypatch.context() as patch:
        patch.setattr(persistence, "_write_atomic", fault_writer)
        with pytest.raises(persistence.DocumentationSceneError, match="failed to write documentation scene"):
            store.commit(request)
    assert calls["reached"]
    assert not list(store.root.rglob(".tmp-documentation-*"))
    assert_complete(store, before, before)


@pytest.mark.parametrize("failure", ["read_only_directory", "sharing_violation"])
def test_permission_failure_and_retry_apply_once(store, tmp_path, monkeypatch, failure):
    before = snapshot(store); request = request_for(store, {"title": "retry permission"})
    def denied(*args, **kwargs):
        error = PermissionError(errno.EACCES, "Access denied")
        if failure == "sharing_violation": error.winerror = 32
        raise error
    with monkeypatch.context() as patch:
        patch.setattr(persistence.tempfile if failure == "read_only_directory" else persistence.os,
                      "mkstemp" if failure == "read_only_directory" else "replace", denied)
        # Exercise the real retry loop, without waiting through its backoff in a fault test.
        patch.setattr(persistence.time, "sleep", lambda delay: None)
        with pytest.raises(persistence.DocumentationSceneError, match="failed to write documentation scene"):
            store.commit(request)
    assert not list(store.root.rglob(".tmp-documentation-*"))
    assert_complete(store, before, before)
    receipt = store.commit(request); after = snapshot(store)
    assert store.values()["title"] == "retry permission"
    assert store.commit(request) == receipt
    assert_complete(store, after, after)


def test_two_process_writers_have_one_winner_and_correct_receipts(store, tmp_path):
    before = snapshot(store)
    requests = [request_for(store, {"title": text}) for text in ("writer A", "writer B")]
    children = [start(tmp_path, store, point="race", request=request) for request in requests]
    try:
        deadline = time.monotonic() + 15
        while not any((control / "ready").exists() for _, control in children) and time.monotonic() < deadline:
            if all(process.poll() is not None for process, _ in children): break
            time.sleep(.01)
        assert any((control / "ready").exists() for _, control in children), [
            (control / "child.log").read_text(errors="replace") for _, control in children]
        # A future interprocess lock may correctly keep the second writer outside this seam.
        # Release after a bounded overlap window; do not require the race defect to be present.
        deadline = time.monotonic() + 1
        while not all((control / "ready").exists() or process.poll() is not None for process, control in children) and time.monotonic() < deadline:
            time.sleep(.01)
        candidates = [post_image(tmp_path, control) for _, control in children if (control / "candidate.json").exists()]
        for _, control in children: (control / "go").touch()
        results = [finish(*child) for child in children]
    finally:
        for process, _ in children:
            if process.poll() is None: process.kill(); process.wait(timeout=5)
    assert_complete(store, candidates[0], candidates[-1])
    successful = [i for i, result in enumerate(results) if result["ok"]]
    refused = [result for result in results if not result["ok"]]
    assert len(successful) == 1 and len(refused) == 1, results
    assert refused[0]["code"] == "stale_revision", results
    winner = successful[0]; after = snapshot(store)
    assert store.commit(requests[winner]) == results[winner]["result"]
    with pytest.raises((commands.DocumentEditError, persistence.DocumentationSceneConflictError)):
        store.commit(requests[1-winner])
    assert_complete(store, before, after)


@pytest.mark.parametrize("point", ["before_backup", "after_backup", "before_replace", "after_replace"])
def test_interrupted_first_migration_preserves_original_bytes(store, tmp_path, point):
    original = legacy(store); before = snapshot(store)
    request = request_for(store, {"title": "migration"})
    process, control = start(tmp_path, store, point=point, request=request)
    wait_at(process, control)
    staged = post_image(tmp_path, control) if (control / "candidate.json").exists() else before
    finish(process, control, kill=True)
    backup = store.path.with_name("documentation-scene.v7.json")
    assert store.path.read_bytes() == original or backup.read_bytes() == original
    assert_complete(store, before, staged)
    store.commit(request); after = snapshot(store)
    assert backup.read_bytes() == original and loaded(store)["scene"]["schemaVersion"] == 8
    assert_complete(store, after, after)


def test_newer_schema_is_refused_without_touching_original_or_backup(store):
    future = json.loads(store.path.read_bytes()); future["schemaVersion"] = 9
    data = commands.canonical_bytes(future); store.path.write_bytes(data)
    backup = store.path.with_name("documentation-scene.v7.json"); backup.write_bytes(b"previous original")
    with pytest.raises(persistence.DocumentationSceneError, match="unsupported documentation scene schema"):
        loaded(store)
    assert store.path.read_bytes() == data and backup.read_bytes() == b"previous original"
    assert_complete(store, data, data, refused=persistence.DocumentationSceneError)


def test_fresh_process_reads_scene_history_and_receipts_exactly(store, tmp_path):
    request = request_for(store, {"title": "restart"})
    process, control = start(tmp_path, store, request=request)
    result = finish(process, control); assert result["ok"], result
    before = snapshot(store)
    process, control = start(tmp_path, store, action="read")
    result = finish(process, control); assert result["ok"], result
    assert commands.canonical_bytes(result["result"]) == before
    assert result["result"]["scene"]["receipts"][request["requestId"]]["receipt"]["revision"] == 2
    assert_complete(store, before, before)


def test_restoring_versioned_backup_to_another_store_recovers_pre_migration_publication(store, tmp_path):
    original = legacy(store); before = snapshot(store); values = store.values()
    store.commit(request_for(store, {"title": "migrated"}))
    restored = SceneHarness(tmp_path / "restored"); restored.path.parent.mkdir(parents=True)
    restored.path.write_bytes(store.path.with_name("documentation-scene.v7.json").read_bytes())
    assert restored.path.read_bytes() == original and restored.values() == values
    assert_complete(restored, before, before)


def test_retained_receipt_survives_later_commands(store):
    request = request_for(store, {"title": "first"}); receipt = store.commit(request)
    store.commit(request_for(store, {"title": "later", "caption": "later"}))
    before = snapshot(store)
    assert store.commit(request) == receipt
    assert_complete(store, before, before)


def test_evicted_receipt_cannot_apply_its_old_preimage_again(store, monkeypatch):
    # Shrink only the retention window: exercise the real eviction/revalidation path without 1,000 fsyncs.
    monkeypatch.setattr(commands, "RECEIPT_LIMIT", 2)
    request = request_for(store, {"title": "first"}); store.commit(request)
    for value in ("second", "third"): store.commit(request_for(store, {"title": value}))
    before = snapshot(store)
    assert request["requestId"] not in loaded(store)["scene"]["receipts"]
    with pytest.raises(commands.DocumentEditError) as error: store.commit(request)
    assert error.value.code == "content_hash_mismatch"
    assert_complete(store, before, before)
