"""Prepare task, publication, protocol and many-part regression tests."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import threading

import numpy as np
import pytest

from tests.model_import_test_support import Fixture, module, textured_box
from tests.model_import_recipe_support import recipe

prepare = module("prepare")
runner = module("runner")
host = module("prepare_runner")
protocol = module("prepare_protocol")
ModelImportError = module("errors").ModelImportError
DEPENDENCIES = Path(np.__file__).resolve().parent.parent


def job_with_recipe(tmp_path, payload=None, raw=None):
    job = tmp_path / "job"
    job.mkdir()
    (job / "source.bin").write_bytes(textured_box().bytes() if payload is None else payload)
    (job / "recipe.json").write_bytes(module("validation").json_bytes(recipe() if raw is None else raw))
    return job


def in_process(monkeypatch):
    def execute(job, dependencies, task, event, timeout):
        assert task == "prepare"
        host._cancelled(event)
        prepare.execute_prepare(job)
    monkeypatch.setattr(host, "_launch", execute)


def test_prepare_task_uses_existing_inspect_cache_and_freezes_files(tmp_path, monkeypatch):
    job = job_with_recipe(tmp_path)
    module("worker_task").execute_inspect(job)
    snapshot = {name: (job / name).read_bytes() for name in ("parts.npz", "cache.json", "summary.json", "result.json")}
    monkeypatch.setattr(module("worker_task"), "execute_inspect",
                        lambda *a: pytest.fail("re-inspected existing cache"))
    result = prepare.execute_prepare(job)
    draft = protocol.read_draft_output(job / "output")
    assert result == prepare.prepare_summary(draft)
    assert draft["recipe"] == module("recipe").normalize_recipe(recipe())
    assert all((job / name).read_bytes() == data for name, data in snapshot.items())
    assert sorted(p.name for p in (job / "output").iterdir()) == sorted([*protocol.DRAFT_FILES, "manifest.json"])
    assert result["triangles"] == 12
    with pytest.raises(ModelImportError):
        prepare.execute_prepare(job)


def test_many_tiny_primitives_twelve_copies_bounded_and_paged(tmp_path):
    fixture = Fixture()
    primitive = fixture.triangle([[0, 0, 0], [.001, 0, 0], [0, .001, .001]])
    fixture.document["meshes"][0]["primitives"] = [deepcopy(primitive) for _ in range(3000)]
    job = job_with_recipe(tmp_path, fixture.bytes(), recipe(copies=[{"x": i * .002} for i in range(12)]))
    result = prepare.execute_prepare(job)
    assert result["partsTotal"] == result["triangles"] == 36000
    assert len(result["parts"]) == 64 and result["nextPartsOffset"] == 64
    assert len(module("validation").json_bytes(result)) <= 48 * 1024
    draft = protocol.read_draft_output(job / "output")
    assert draft["partsTotal"] == 36000
    assert sum(1 for _ in (job / "output" / "parts.jsonl").open("rb")) == 36000
    from ai_inspector.industrial_assets.primitives import verify, gltf_json
    payload = (job / "output" / "model.glb").read_bytes()
    assert len(gltf_json(payload)["nodes"]) == 36000
    assert verify(payload, draft["dimensions"])["triangles"] == 36000


@pytest.mark.parametrize("cached", [False, True])
def test_real_prepare_worker_and_deterministic_identity(tmp_path, cached):
    source = tmp_path / "box.glb"
    source.write_bytes(textured_box().bytes())
    cache_dir = None
    if cached:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "source.bin").write_bytes(source.read_bytes())
        module("worker_task").execute_inspect(cache_dir)
    first, second = tmp_path / "first", tmp_path / "second"
    a = host.prepare_draft(source, recipe(), first, dependency_root=DEPENDENCIES, cache_dir=cache_dir)
    b = host.prepare_draft(source, recipe(), second, dependency_root=DEPENDENCIES, cache_dir=cache_dir)
    assert a == b and a["draftId"].startswith("md-")
    assert all((first / name).read_bytes() == (second / name).read_bytes() for name in
               (*protocol.DRAFT_FILES, "manifest.json"))
    assert not list(tmp_path.glob(".model-prepare-*")) and not list(tmp_path.glob("*.prepare-lock"))


def test_host_preexisting_destination_never_changes(tmp_path, monkeypatch):
    source = tmp_path / "source.glb"
    source.write_bytes(textured_box().bytes())
    destination = tmp_path / "draft"
    destination.mkdir()
    (destination / "keep").write_bytes(b"original")
    monkeypatch.setattr(host, "_launch", lambda *a: pytest.fail("spawned"))
    with pytest.raises(ModelImportError) as caught:
        host.prepare_draft(source, recipe(), destination, dependency_root=DEPENDENCIES)
    assert caught.value.code == "model_destination_exists"
    assert (destination / "keep").read_bytes() == b"original"


@pytest.mark.parametrize("when", ["before", "after_worker", "after_rename"])
def test_cancelled_prepare_never_retains_a_draft(tmp_path, monkeypatch, when):
    source = tmp_path / "source.glb"
    source.write_bytes(textured_box().bytes())
    destination, event = tmp_path / "draft", threading.Event()
    in_process(monkeypatch)
    if when == "before":
        event.set()
    elif when == "after_worker":
        launch = host._launch
        def cancel_after(*args):
            launch(*args)
            event.set()
        monkeypatch.setattr(host, "_launch", cancel_after)
    else:
        rename = Path.rename
        def cancel_after(self, target):
            result = rename(self, target)
            event.set()
            return result
        monkeypatch.setattr(Path, "rename", cancel_after)
    with pytest.raises(ModelImportError) as caught:
        host.prepare_draft(source, recipe(), destination, event, dependency_root=DEPENDENCIES)
    assert caught.value.code == "model_cancelled"
    assert not destination.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.glb"]


def test_late_async_prepare_cancel_removes_only_its_published_folder(tmp_path, monkeypatch):
    destination = tmp_path / "draft"
    finished, release = threading.Event(), threading.Event()
    def complete(*args, _published=None, **kwargs):
        destination.mkdir()
        (destination / "draft.json").write_bytes(b"owned")
        _published.set()
        finished.set()
        release.wait(3)
        return {}
    monkeypatch.setattr(host, "prepare_draft", complete)
    async def exercise():
        task = asyncio.create_task(host.prepare_draft_async(tmp_path / "source", recipe(), destination))
        while not finished.is_set():
            await asyncio.sleep(.001)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(exercise())
    assert not destination.exists()


@pytest.mark.parametrize("cancel", [False, True])
def test_real_prepare_timeout_or_cancel_kills_joins_and_cleans(tmp_path, monkeypatch, cancel):
    source = tmp_path / "source.glb"
    source.write_bytes(textured_box().bytes())
    stub = tmp_path / "stub.py"
    stub.write_bytes(b"import time\nfrom pathlib import Path\nPath('output').mkdir()\ntime.sleep(30)\n")
    monkeypatch.setattr(runner, "_WORKER", stub)
    processes, original = [], runner.subprocess.Popen
    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(runner.subprocess, "Popen", capture)
    event = threading.Event()
    timer = threading.Timer(.2, event.set) if cancel else None
    if timer:
        timer.start()
    try:
        with pytest.raises(ModelImportError) as caught:
            host.prepare_draft(source, recipe(), tmp_path / "draft", event,
                               dependency_root=DEPENDENCIES, timeout=3 if cancel else .2)
        assert caught.value.code == ("model_cancelled" if cancel else "model_timeout")
    finally:
        if timer:
            timer.join()
    assert processes and processes[0].poll() is not None
    assert not (tmp_path / "draft").exists()
    assert not list(tmp_path.glob(".model-prepare-*"))


def rewrite_manifest(directory):
    files = {name: {"bytes": (directory / name).stat().st_size,
                    "sha256": sha256((directory / name).read_bytes()).hexdigest()} for name in protocol.DRAFT_FILES}
    (directory / "manifest.json").write_bytes(module("validation").json_bytes({"schemaVersion": 2, "files": files}))


@pytest.mark.parametrize("corruption", ["hash", "schema", "parts", "credit", "unexpected", "size", "path"])
def test_host_rejects_corrupted_outputs(tmp_path, corruption):
    job = job_with_recipe(tmp_path)
    prepare.execute_prepare(job)
    directory = job / "output"
    if corruption == "hash":
        (directory / "model.glb").write_bytes(b"wrong")
    elif corruption == "schema":
        draft = json.loads((directory / "draft.json").read_bytes())
        draft["triangles"] = True
        (directory / "draft.json").write_bytes(module("validation").json_bytes(draft))
        rewrite_manifest(directory)
    elif corruption == "parts":
        (directory / "parts.jsonl").write_bytes(b'{"key":"p999","name":"paint","triangles":12}\n')
        rewrite_manifest(directory)
    elif corruption == "credit":
        (directory / "CREDITS.txt").write_bytes(b"wrong")
        rewrite_manifest(directory)
    elif corruption == "unexpected":
        (directory / "extra").write_bytes(b"wrong")
    else:
        manifest = json.loads((directory / "manifest.json").read_bytes())
        if corruption == "size":
            manifest["files"]["model.glb"]["bytes"] = 31 * 1024 * 1024
        else:
            manifest["files"]["../outside"] = manifest["files"].pop("model.glb")
        (directory / "manifest.json").write_bytes(module("validation").json_bytes(manifest))
    with pytest.raises(ModelImportError) as caught:
        protocol.read_draft_output(directory)
    assert caught.value.code == "model_worker_failed"


def test_cache_cannot_be_used_with_another_source(tmp_path, monkeypatch):
    in_process(monkeypatch)
    job = job_with_recipe(tmp_path)
    module("worker_task").execute_inspect(job)
    source = tmp_path / "other.glb"
    fixture = textured_box()
    fixture.document["asset"]["generator"] = "different bytes"
    source.write_bytes(fixture.bytes())
    with pytest.raises(ModelImportError) as caught:
        host.prepare_draft(source, recipe(), tmp_path / "draft", dependency_root=DEPENDENCIES, cache_dir=job)
    assert caught.value.code == "model_cache_invalid"
    assert not (tmp_path / "draft").exists()


def test_worker_read_paths_stay_inside_job(tmp_path, monkeypatch):
    job = job_with_recipe(tmp_path)
    reads, original = [], Path.open
    def capture(self, mode="r", *args, **kwargs):
        if "r" in mode:
            reads.append(self.resolve())
        return original(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", capture)
    prepare.execute_prepare(job)
    assert reads and all(path.is_relative_to(job.resolve()) for path in reads)


def test_source_cache_is_not_mutated_in_memory():
    payload = textured_box().bytes()
    source = module("reader").read_model(payload)
    positions = source.parts[0].positions.copy()
    materials = deepcopy(source.materials)
    prepare.build_draft(source, recipe(rotate={"z": 50}, copies=[{}, {}], parts=[
        {"select": {"all": True}, "material": {"texture": "drop"}}]), payload)
    np.testing.assert_array_equal(source.parts[0].positions, positions)
    assert source.materials == materials
